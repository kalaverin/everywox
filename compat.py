from const import WOX_SDK_PATH

try:
    from wox import Wox

except ImportError:
    import sys

    sys.path = [WOX_SDK_PATH] + sys.path
    from wox import Wox
