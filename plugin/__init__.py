from calibre.customize import InterfaceActionBase


class KindleAnnotationSync(InterfaceActionBase):
    name = "Kindle Annotation Sync"
    description = "Sync Kindle highlights and notes (My Clippings.txt) into calibre's book annotations"
    supported_platforms = ["windows", "osx", "linux"]
    author = "Artyom Tsoy"
    version = (1, 0, 0)
    minimum_calibre_version = (7, 0, 0)
    actual_plugin = "calibre_plugins.kindle_annotation_sync.ui:SyncAction"
