"""
Tempo Version Information
"""

__version__ = "2.2.0"
__author__ = "Ahmed Elkholy"
__email__ = "ahm_elkholy@outlook.com"
__description__ = "A comprehensive cross-platform productivity timer application"
__url__ = "https://github.com/ahmelkholy/tempo"

# Version components
VERSION_MAJOR = 2
VERSION_MINOR = 2
VERSION_PATCH = 0
VERSION_INFO = (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)

# Build and release information
BUILD_DATE = "2026-11-27"
RELEASE_CHANNEL = "stable"


def get_version():
    """Return the version string."""
    return __version__


def get_version_info():
    """Return the version as a tuple."""
    return VERSION_INFO
