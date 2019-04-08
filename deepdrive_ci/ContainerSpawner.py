from tenacity import retry, retry_if_exception_type, stop_after_attempt
import arrow, boto3, datetime, docker, logging, random, time
from ue4helpers import DockerUtils


class HostSelectionRestart(Exception):
	'''
	Exception type indicating that container host selection failed and should restart
	'''
	pass


class ContainerSpawner(object):
	'''
	Provides functionality for selecting an appropriate Docker container host from an
	available pool of Amazon EC2 instances and starting a container on the selected host
	'''
	
	def __init__(self, label, max_containers = 1, startup_time = 30):
		'''
		Creates a new ContainerSpawner instance.
		
		`label` specifies the label that is used to identify spawned containers. This label
		is also used when identifying existing containers, which ensures arbitrary containers
		(e.g. system support services) are not counted when determining the occupancy of a
		given container host.
		
		`max_containers` specifies the default value for the maximum number of containers that
		any given container host supports executing concurrently. (This can be overridden on a
		per-host basis.)
		
		`startup_time` specifies the time (in seconds) that we wait for the Docker daemon to
		finish starting up on freshly-booted container hosts.
		'''
		self._label = label
		self._max_containers = max_containers
		self._startup_time = startup_time
	
	@retry(retry=retry_if_exception_type(HostSelectionRestart), stop=stop_after_attempt(5))
	def spawn_container(self, image, tag = None, capacity = None, tls = None, options = {}):
		'''
		Selects an appropriate container host from an available pool and starts a container.
		
		`image` is the name of the Docker image that the container will be based on.
		
		`tag` should be either a tuple containing an EC2 tag name and a list of acceptable values,
		which will be used to filter the list of EC2 instances and identify our pool, or None if
		we don't want to perform any filtering of the available EC2 instances.
		
		`capacity` should be either a string containing the EC2 tag name that is used to determine
		the maximum number of containers that an instance supports executing concurrently, or None
		if we want to fall back to our default value for all instances. (The default value will still
		be used for any instances that do not have a value set for the tag if one was specified.)
		
		`tls` should be either an instance of `docker.tls.TLSConfig` or None for unencrypted
		TCP connections.
		
		`options` should be a dictionary of keyword arguments to pass to the
		`ue4helpers.DockerUtils.start_for_exec()` function.
		'''
		
		# Retrieve the list of available EC2 instances and filter them to identify our host pool
		logging.info('Retrieving container host pool details...')
		ec2 = boto3.resource('ec2')
		pool = ec2.instances.filter(Filters = None if tag is None else [
			{
				'Name': 'tag:{}'.format(tag[0]),
				'Values': tag[1]
			}
		])
		
		# Retrieve the details for each of the instances in our pool
		instances = list([self._get_instance_details(instance, capacity, tls) for instance in pool])
		logging.info('Retrieved details for {} hosts in our pool'.format(len(instances)))
		
		# Determine which instances are running and have available capacity and which instances are stopped
		running = list([instance for instance in instances if self._has_capacity(instance)])
		stopped = list([instance for instance in instances if instance['running'] == False])
		selected = None
		if len(running) > 0:
			
			# We have at least one running instance with available capacity, so we select the instance
			# with the fewest running CI jobs, using random selection to break ties
			minContainers = min([instance['containers'] for instance in running])
			candidates = [instance for instance in running if instance['containers'] == minContainers]
			selected = random.choice(candidates)
			
		elif len(stopped) > 0:
			
			# We have at least one stopped instance that we can start, so select one randomly and start it
			selected = random.choice(stopped)
			
			# Attempt to start the instance
			logging.info('Starting stopped instance {}...'.format(selected['instance'].id))
			selected['instance'].start()
			selected['instance'].wait_until_running()
			
			# Wait until the Docker daemon has had a chance to start
			time.sleep(self._startup_time)
			
			# Attempt to connect to the Docker daemon and query the container count
			# (If this fails then either the daemon crashed or the instance has been shutdown)
			selected = self._get_instance_details(selected['instance'], capacity, tls)
			if selected['docker'] == None:
				logging.info('Failed to connect to the Docker daemon, restarting selection process...')
				raise HostSelectionRestart
			
		else:
			
			# We have no available capacity and need to wait before restarting the selection process
			logging.info('No capacity currently available, triggering backdown timer...')
			backdown = random.uniform(60, 180)
			time.sleep(backdown)
			raise HostSelectionRestart
		
		# Attempt to start a container on the selected host
		container = None
		try:
			logging.info('Starting container on instance {}...'.format(selected['instance'].id))
			container = DockerUtils.start_for_exec(selected['docker'], image, labels=[self._label], **options)
		except:
			logging.info('Failed to start container, restarting selection process...')
			raise HostSelectionRestart
		
		# Verify that we have not inadvertently exceeded the maximum occupancy of the host due to a timing error
		containers = self._running_containers(selected)
		if len(containers) > selected['capacity']:
			
			# Occupancy has been exceeded, so use container creation times to determine if our container is to blame
			created = sorted([arrow.get(c.attrs['Created']) for c in containers])
			surplus = created[ (len(containers) - self._max_containers)-1 : ]
			if arrow.get(container.attrs['Created']) in surplus:
				logging.info('Timing error detected, stopping surplus container...')
				container.stop()
				raise HostSelectionRestart
		
		return container
	
	
	# "Private" methods
	
	def _running_containers(self, instance):
		'''
		Queries the Docker daemon on the specified container host to retrieve the list of running containers.
		Containers are only included if they have the label that we use to spawn new containers, which ensures
		arbitrary containers (e.g. system support services) are ignored.
		'''
		return instance['docker'].containers.list(filters={'label': self._label})
	
	def _has_capacity(self, instance):
		'''
		Determines if a container host has a running Docker daemon and has not reached maximum occupancy
		'''
		return instance['running'] == True and instance['docker'] is not None and instance['containers'] < instance['capacity']
	
	def _get_instance_details(self, instance, capacity = None, tls = None):
		'''
		Retrieves the details for an EC2 instance, including the number of running Docker containers.
		
		`instance` should be an instance of `boto3.EC2.Instance`.
		
		`capacity` should be either a string containing the EC2 tag name that is used to determine the
		maximum number of containers that an instance supports executing concurrently, or None if we
		want to fall back to our default value for all instances. (The default value will still be used
		if the instance does not have a value set for the specified tag.)
		
		`tls` should be either an instance of `docker.tls.TLSConfig` or None for unencrypted
		TCP connections.
		'''
		
		# Determine if we have an instance-specific capacity override
		detectedCapacity = self._max_containers
		capacityTags = [tag for tag in instance.tags if tag['Key'] == capacity]
		if capacity is not None and len(capacityTags) > 0:
			detectedCapacity = int(capacityTags[0]['Value'])
		
		# Create our details object
		details = {
			'instance': instance,
			'capacity': detectedCapacity,
			'running': instance.state['Name'] == 'running',
			'docker': None,
			'containers': 0
		}
		
		# If the instance is running, attempt to retrieve the container count from the Docker daemon
		if details['running'] == True:
			try:
				
				# If the instance has only just booted up then wait until the Docker daemon has had a chance to start
				uptime = (datetime.datetime.now(datetime.timezone.utc) - instance.launch_time).total_seconds()
				if uptime < self._startup_time:
					time.sleep(self._startup_time - uptime)
				
				# Attempt to connect to the Docker daemon
				ip = instance.public_ip_address
				port = 2376 if tls is not None else 2375
				client = docker.DockerClient(base_url='tcp://{}:{}'.format(ip, port), tls=tls)
				client.ping()
				
				# If the connection was successful, store the container count and Docker client
				details['docker'] = client
				details['containers'] = len(self._running_containers(details))
				
			except:
				
				# Could not connect to the Docker daemon
				pass
		
		return details
