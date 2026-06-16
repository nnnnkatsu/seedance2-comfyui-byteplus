from .seedance2_nodes import (
    NODE_CLASS_MAPPINGS as _N,
    NODE_DISPLAY_NAME_MAPPINGS as _D,
)
from .seedance2_video_saver import (
    NODE_CLASS_MAPPINGS as _SN,
    NODE_DISPLAY_NAME_MAPPINGS as _SD,
)
from .seedance2_s3_nodes import (
    NODE_CLASS_MAPPINGS as _S3N,
    NODE_DISPLAY_NAME_MAPPINGS as _S3D,
)

NODE_CLASS_MAPPINGS = {**_N, **_SN, **_S3N}
NODE_DISPLAY_NAME_MAPPINGS = {**_D, **_SD, **_S3D}
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
