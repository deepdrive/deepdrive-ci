from .TargetPlatform import TargetPlatform

class PlatformDefaults(object):
	'''
	The default configuration values for each of our supported container platforms
	'''
	
	@staticmethod
	def default_image(platform):
		'''
		Returns the default container image for the specified platform
		'''
		return {
			
			TargetPlatform.Linux: 'adamrehn/ue4-full:4.21.2-cudagl10.0',
			TargetPlatform.Windows: 'adamrehn/ue4-full:4.21.2-ltsc2019'
			
		}[platform]
