from .ContainerSpawner import ContainerSpawner
from .PlatformDefaults import PlatformDefaults
from ue4helpers import AWSUtils, DockerUtils
import docker, logging, os, tempfile
from termcolor import colored


class JobRunner(object):
	'''
	Provides functionality for running CI jobs
	'''
	
	@staticmethod
	def run_job(job_logic, platform, image = None, container_options = {}):
		'''
		Starts a Docker container on an appropriate EC2 host and runs the supplied CI job logic.
		
		`job_logic` should be a callable that accepts the following parameters:
		- `container`: an instance of `docker.models.containers.Container` representing the Docker container for the job
		- `client`: an instance of `docker.client.DockerClient` that can be used to communicate with the Docker daemon
		
		`platform` should specify the target platform for the job, using a value from the `TargetPlatform` constants.
		
		`image` can be used to specify the container image to use. If `None` then the platform default will be used.
		
		`container_options` can be used to specify a dictionary of keyword arguments to pass to the
		`ue4helpers.DockerUtils.start_for_exec()` function.
		'''
		
		# Write log output to stderr
		logging.basicConfig(
			format = colored('[' + os.path.basename(__file__) + ' {name}]: {message}', color='yellow', attrs=['bold']),
			level = logging.INFO,
			style = '{'
		)
		
		# Use the default container image for the target platform if no image was specified
		if image is None:
			image = PlatformDefaults.default_image(platform)
		
		# Start a Docker container within which the CI job will be run
		# (For jobs that actually build and run their own custom container images, this container will
		#  just act as a proxy for our build when the CI system queries the container host's occupancy)
		spawner = ContainerSpawner('io.deepdrive.ci')
		container = spawner.spawn_container(image, ('ci-platform', [platform]), 'ci-capacity', None, container_options)
		with DockerUtils.automatically_stop(container):
			
			# Run the actual logic for the CI job
			job_logic(container, container.client)
