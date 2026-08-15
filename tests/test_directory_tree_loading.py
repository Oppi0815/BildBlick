from pathlib import Path

import bildbetrachter
from bildbetrachter import ImageViewer, STATUS_BUSY, STATUS_READY


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


def test_volume_refreshes_preserve_the_selected_directory_for_later_mounts(tmp_path):
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
    viewer._expand_volumes_node = lambda: None
    viewer._expand_initial_path = restored_paths.append

    # Each event represents a volume becoming available later (Data 0, then
    # B650).  The selected folder remains the active tree target.
    for _mounted_volume in ("Data 0", "B650"):
        viewer._refresh_volumes_tree()

    assert recreated == [True, True]
    assert restored_paths == [selected_directory, selected_directory]


def test_connect_network_drive_opens_finders_connect_to_server_dialog(monkeypatch):
    viewer = ImageViewer.__new__(ImageViewer)
    started = []
    monkeypatch.setattr(bildbetrachter.sys, "platform", "darwin")
    monkeypatch.setattr(
        bildbetrachter.subprocess,
        "Popen",
        lambda command, **kwargs: started.append((command, kwargs)),
    )

    viewer._connect_network_drive()

    assert started == [
        (
            [
                "osascript",
                "-e",
                'tell application "Finder" to activate',
                "-e",
                'tell application "System Events" to keystroke "k" using {command down}',
            ],
            {
                "stdout": bildbetrachter.subprocess.DEVNULL,
                "stderr": bildbetrachter.subprocess.DEVNULL,
                "start_new_session": True,
            },
        )
    ]


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
