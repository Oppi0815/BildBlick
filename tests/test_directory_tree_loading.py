from pathlib import Path

import bildbetrachter
from bildbetrachter import ImageViewer, STATUS_BUSY, STATUS_READY, network_mount_roots


class _Index:
    def __init__(self, valid: bool):
        self._valid = valid

    def isValid(self) -> bool:
        return self._valid


class _DelayedDirectoryModel:
    def __init__(self, delayed_path: Path):
        self.delayed_path = delayed_path
        self.target_is_loaded = False

    def index(self, path: str) -> _Index:
        is_target = Path(path) == self.delayed_path
        return _Index(not is_target or self.target_is_loaded)


class _Tree:
    def __init__(self):
        self.expanded = []
        self.current_index = None
        self.scrolled_to = None

    def expand(self, index):
        self.expanded.append(index)

    def setCurrentIndex(self, index):
        self.current_index = index

    def scrollTo(self, index):
        self.scrolled_to = index

    def currentIndex(self):
        return self.current_index or _Index(False)


class _RetryTimer:
    def __init__(self):
        self.active = False
        self.started_with = []

    def isActive(self) -> bool:
        return self.active

    def start(self, interval: int):
        self.active = True
        self.started_with.append(interval)

    def stop(self):
        self.active = False


def test_directory_tree_retries_a_path_until_its_model_index_is_loaded(tmp_path):
    target = tmp_path / "Volumes" / "Data 0"
    target.mkdir(parents=True)
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.directory_model = _DelayedDirectoryModel(target)
    viewer.directory_tree = _Tree()
    viewer._tree_path_retry_timer = _RetryTimer()
    viewer._pending_tree_path = None

    viewer._expand_initial_path(target)

    assert viewer._pending_tree_path == target
    assert viewer._tree_path_retry_timer.started_with == [100]
    assert viewer.directory_tree.current_index is None

    viewer.directory_model.target_is_loaded = True
    viewer._retry_pending_tree_path()  # Simulates QFileSystemModel.directoryLoaded.

    assert viewer._pending_tree_path is None
    assert viewer.directory_tree.current_index is not None
    assert viewer.directory_tree.scrolled_to is viewer.directory_tree.current_index
    assert not viewer._tree_path_retry_timer.active


def test_volumes_node_is_expanded_without_a_start_path():
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.directory_model = _DelayedDirectoryModel(Path("/not-the-volumes-node"))
    viewer.directory_tree = _Tree()

    viewer._expand_volumes_node()

    assert len(viewer.directory_tree.expanded) == 1


def test_mount_refreshes_preserve_the_selected_directory_for_later_mounts(tmp_path, monkeypatch):
    selected_directory = tmp_path / "Volumes" / "Data 0" / "Fotos"
    selected_directory.mkdir(parents=True)
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.directory_tree = _Tree()
    viewer.directory_tree.current_index = _Index(True)

    class _Model:
        @staticmethod
        def filePath(_index):
            return str(selected_directory)

    viewer.directory_model = _Model()
    viewer.current_directory = selected_directory
    recreated = []
    restored_paths = []
    viewer._create_directory_model = lambda: recreated.append(True)
    viewer._sync_network_mount_watch_paths = lambda: None
    viewer._expand_network_mount_nodes = lambda: None
    viewer._expand_initial_path = restored_paths.append
    snapshots = iter(((Path("/Volumes/Data 0"),), (Path("/Volumes/B650"),)))
    monkeypatch.setattr(bildbetrachter, "network_mount_paths", lambda: next(snapshots))
    viewer._network_mount_snapshot = ()

    # Each event represents a volume becoming available later (Data 0, then
    # B650).  The selected folder remains the active tree target.
    for _mounted_volume in ("Data 0", "B650"):
        viewer._refresh_network_mounts_tree()

    assert recreated == [True, True]
    assert restored_paths == [selected_directory, selected_directory]


def test_connect_network_location_uses_macos_finder_mounting():
    assert bildbetrachter.network_mount_command(
        "smb://B650/Data%200", platform="darwin"
    ) == ["open", "smb://B650/Data%200"]


def test_connect_network_location_uses_gio_on_linux():
    assert bildbetrachter.network_mount_command(
        "sftp://mac.local/", platform="linux"
    ) == ["gio", "mount", "sftp://mac.local/"]


def test_unchanged_mount_snapshot_does_not_recreate_the_directory_model(monkeypatch):
    viewer = ImageViewer.__new__(ImageViewer)
    snapshot = (Path("/run/user/1000/gvfs/sftp:host=mac.local"),)
    viewer._network_mount_snapshot = snapshot
    viewer._sync_network_mount_watch_paths = lambda: None
    viewer._create_directory_model = lambda: (_ for _ in ()).throw(AssertionError())
    viewer._refresh_network_navigation = lambda: (_ for _ in ()).throw(AssertionError())
    monkeypatch.setattr(bildbetrachter, "network_mount_paths", lambda: snapshot)

    viewer._refresh_network_mounts_tree()


def test_network_navigation_toggle_hides_mount_controls_when_collapsed():
    viewer = ImageViewer.__new__(ImageViewer)

    class _Content:
        visible = None

        def setVisible(self, visible):
            self.visible = visible

    class _ToggleButton:
        arrow = None

        def setArrowType(self, arrow):
            self.arrow = arrow

    viewer.network_navigation_content = _Content()
    viewer.network_toggle_button = _ToggleButton()

    viewer._set_network_navigation_expanded(False)

    assert viewer.network_navigation_content.visible is False
    assert viewer.network_toggle_button.arrow == bildbetrachter.Qt.ArrowType.RightArrow


def test_network_navigation_toggle_shows_mount_controls_when_expanded():
    viewer = ImageViewer.__new__(ImageViewer)

    class _Content:
        visible = None

        def setVisible(self, visible):
            self.visible = visible

    class _ToggleButton:
        arrow = None

        def setArrowType(self, arrow):
            self.arrow = arrow

    viewer.network_navigation_content = _Content()
    viewer.network_toggle_button = _ToggleButton()

    viewer._set_network_navigation_expanded(True)

    assert viewer.network_navigation_content.visible is True
    assert viewer.network_toggle_button.arrow == bildbetrachter.Qt.ArrowType.DownArrow


def test_network_navigation_toggle_keeps_the_active_network_directory():
    viewer = ImageViewer.__new__(ImageViewer)
    active_directory = Path("/run/user/1000/gvfs/sftp:host=mac.local/Users/horst/Austausch")
    viewer.current_directory = active_directory

    class _Content:
        def setVisible(self, _visible):
            pass

    class _ToggleButton:
        def setArrowType(self, _arrow):
            pass

    viewer.network_navigation_content = _Content()
    viewer.network_toggle_button = _ToggleButton()

    viewer._set_network_navigation_expanded(False)

    assert viewer.current_directory == active_directory


def test_network_mount_label_uses_gvfs_host_alias():
    assert bildbetrachter.network_mount_label(
        Path("/run/user/1000/gvfs/sftp:host=mac.local")
    ) == "mac.local"


def test_network_mount_paths_shows_gvfs_but_not_local_mnt(monkeypatch):
    gvfs = Path("/run/user/1000/gvfs")
    local_mnt = Path("/mnt/local-disk")
    monkeypatch.setattr(bildbetrachter.sys, "platform", "linux")

    paths = bildbetrachter.network_mount_paths(
        (gvfs, Path("/mnt")),
        iterdir=lambda path: iter((gvfs / "sftp:host=mac.local",)) if path == gvfs else iter((local_mnt,)),
        mountinfo_text="",
    )

    assert paths == (gvfs / "sftp:host=mac.local",)


def test_network_mount_paths_keeps_real_network_mnt_mount(monkeypatch):
    monkeypatch.setattr(bildbetrachter.sys, "platform", "linux")
    paths = bildbetrachter.network_mount_paths(
        (Path("/mnt"),),
        iterdir=lambda _path: iter(()),
        mountinfo_text="42 1 0:1 / /mnt/share rw - cifs //server/share rw",
    )
    assert paths == (Path("/mnt/share"),)


def test_network_mount_roots_preserves_macos_volumes():
    roots = network_mount_roots(
        platform="darwin", is_dir=lambda path: path == Path("/Volumes")
    )

    assert roots == (Path("/Volumes"),)


def test_network_mount_roots_uses_existing_linux_locations_only():
    gvfs = Path("/run/user/1000/gvfs")
    roots = network_mount_roots(
        platform="linux",
        uid=1000,
        username="mint-user",
        is_dir=lambda path: path in {gvfs, Path("/mnt")},
    )

    assert roots == (gvfs, Path("/mnt"))


def test_linux_mount_watches_gvfs_parent_when_gvfs_is_missing(monkeypatch):
    viewer = ImageViewer.__new__(ImageViewer)
    monkeypatch.setattr(bildbetrachter.sys, "platform", "linux")
    monkeypatch.setattr(bildbetrachter.os, "getuid", lambda: 1000)
    monkeypatch.setattr(bildbetrachter, "network_mount_roots", lambda: ())
    monkeypatch.setattr(Path, "is_dir", lambda path: path == Path("/run/user/1000"))

    assert viewer._network_mount_watch_paths() == (Path("/run/user/1000"),)


def test_mount_watcher_updates_paths_when_a_mount_is_added_or_removed():
    class _Watcher:
        def __init__(self):
            self.paths = {"/run/user/1000/gvfs", "/mnt/old-share"}
            self.removed = []
            self.added = []

        def directories(self):
            return list(self.paths)

        def removePaths(self, paths):
            self.removed.extend(paths)
            self.paths.difference_update(paths)

        def addPaths(self, paths):
            self.added.extend(paths)
            self.paths.update(paths)

    viewer = ImageViewer.__new__(ImageViewer)
    viewer._volumes_watcher = _Watcher()
    viewer._network_mount_watch_paths = lambda: (
        Path("/run/user/1000/gvfs"),
        Path("/mnt/new-share"),
    )

    viewer._sync_network_mount_watch_paths()

    assert viewer._volumes_watcher.removed == ["/mnt/old-share"]
    assert viewer._volumes_watcher.added == ["/mnt/new-share"]


def test_delayed_thumbnail_job_keeps_the_status_indicator_busy():
    viewer = ImageViewer.__new__(ImageViewer)
    viewer._load_generation = 4
    viewer._directory_loading_generation = 4
    viewer._directory_iterator = None
    viewer._pending_images = [Path("first.jpg"), Path("delayed.jpg")]
    viewer._prepare_index = 2
    viewer._next_job_index = 2
    viewer._completed_jobs = 1
    viewer._active_jobs = 1

    state, _text = viewer._status_with_directory_loading_guard(STATUS_READY, None)

    assert state == STATUS_BUSY

    viewer._completed_jobs = 2
    viewer._active_jobs = 0
    state, _text = viewer._status_with_directory_loading_guard(STATUS_READY, None)

    assert state == STATUS_READY


def test_obsolete_thumbnail_jobs_do_not_keep_the_status_indicator_busy():
    viewer = ImageViewer.__new__(ImageViewer)
    viewer._load_generation = 5
    viewer._directory_loading_generation = 4
    viewer._directory_iterator = None
    viewer._pending_images = [Path("obsolete.jpg")]
    viewer._prepare_index = 1
    viewer._next_job_index = 1
    viewer._completed_jobs = 0
    viewer._active_jobs = 1

    state, _text = viewer._status_with_directory_loading_guard(STATUS_READY, None)

    assert state == STATUS_READY
