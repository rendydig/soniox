import sounddevice as sd
from PySide6.QtCore import QObject, Signal

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    pyaudio = None

VIRTUAL_OUTPUT_HINTS = ("voicemeeter", "vb-audio", "cable", "voice.ai", "nvidia broadcast", "virtual")
PSEUDO_INPUT_HINTS = ("sound mapper",)
LOOPBACK_INPUT_HINTS = ("stereo mix", "loopback", "what u hear", "wave out", "monitor")
VIRTUAL_INPUT_HINTS = ("voicemeeter", "vb-audio", "cable", "voice.ai", "nvidia broadcast", "virtual")


class DeviceController(QObject):
    """Handles audio device management and selection."""
    
    device_error = Signal(str)
    devices_populated = Signal(list, list, list, list)
    
    def __init__(self):
        super().__init__()
        self._device_ids = []
        self._default_host_id = None
        self._default_speaker_index = None
    
    @staticmethod
    def _is_auto_pick_excluded(name: str) -> bool:
        """True for pseudo, loopback or virtual-cable input devices (auto-pick only)."""
        lowered = name.lower()
        hints = PSEUDO_INPUT_HINTS + LOOPBACK_INPUT_HINTS + VIRTUAL_INPUT_HINTS
        return any(hint in lowered for hint in hints)
    
    @staticmethod
    def _host_device_works(device_id: int) -> bool:
        """Fast format check mirroring the worker's stream settings (16000 Hz mono)."""
        kwargs = dict(device=device_id, samplerate=16000, channels=1, dtype="float32")
        try:
            sd.check_input_settings(**kwargs)
            return True
        except sd.PortAudioError:
            try:
                hostapi = sd.query_devices(device_id)["hostapi"]
                if "wasapi" not in sd.query_hostapis(hostapi)["name"].lower():
                    return False
                kwargs["extra_settings"] = sd.WasapiSettings(auto_convert=True)
                sd.check_input_settings(**kwargs)
                return True
            except Exception:
                return False
        except Exception:
            return False
    
    def _pick_default_host(self, host_ids):
        """Prefer the Windows default input, else the first working non-excluded device."""
        try:
            default_id = sd.query_devices(kind="input")["index"]
        except Exception:
            default_id = None
        
        if default_id in host_ids:
            try:
                name = sd.query_devices(default_id)["name"]
            except Exception:
                name = ""
            if not self._is_auto_pick_excluded(name) and self._host_device_works(default_id):
                return default_id
        
        for idx in host_ids:
            try:
                name = sd.query_devices(idx)["name"]
            except Exception:
                continue
            if self._is_auto_pick_excluded(name):
                continue
            if self._host_device_works(idx):
                return idx
        return None
    
    def _query_loopback_devices(self):
        """Return (labels, items, default_position) for output loopback devices."""
        if pyaudio is None:
            return [], [], None
        
        pa = pyaudio.PyAudio()
        try:
            try:
                default_index = pa.get_default_wasapi_loopback()["index"]
            except Exception:
                default_index = None
            
            devices = list(pa.get_loopback_device_info_generator())
            devices.sort(key=lambda d: (d["index"] != default_index, d["index"]))
            
            usable = []
            for d in devices:
                name = d["name"].replace(" [Loopback]", "")
                if any(hint in name.lower() for hint in VIRTUAL_OUTPUT_HINTS):
                    continue
                sr = int(d["defaultSampleRate"])
                try:
                    works = bool(pa.is_format_supported(
                        sr, input_device=d["index"], input_channels=2, input_format=pyaudio.paFloat32
                    ))
                except Exception:
                    works = False
                usable.append((d["index"], name, sr, works))
            
            default_pos = None
            for pos, (idx, name, sr, works) in enumerate(usable):
                if idx == default_index and works:
                    default_pos = pos
                    break
            if default_pos is None:
                for pos, (idx, name, sr, works) in enumerate(usable):
                    if works:
                        default_pos = pos
                        break
            
            labels = []
            items = []
            for pos, (idx, name, sr, works) in enumerate(usable):
                suffix = " (default)" if pos == default_pos else ""
                labels.append(f"[Loopback] {name} — {sr} Hz{suffix}")
                items.append({"backend": "loopback", "index": idx, "rate": sr, "name": name})
            return labels, items, default_pos
        finally:
            pa.terminate()
    
    def populate_devices(self):
        """Query and populate available audio input devices."""
        try:
            devs = sd.query_devices()
            entries = []
            host_ids = []
            
            for idx, d in enumerate(devs):
                if d.get('max_input_channels', 0) > 0:
                    name = d.get('name', f'Device {idx}')
                    sr = d.get('default_samplerate') or 44100
                    entries.append((idx, name, int(sr)))
                    host_ids.append(idx)
            
            self._default_host_id = self._pick_default_host(host_ids)
            
            host_list = []
            for idx, name, sr in entries:
                suffix = " (default)" if idx == self._default_host_id else ""
                host_list.append(f"[{idx}] {name} — {sr} Hz{suffix}")
            
            speaker_list, speaker_items, default_pos = self._query_loopback_devices()
            self._default_speaker_index = default_pos
            
            self._device_ids = host_ids
            self.devices_populated.emit(host_list, host_ids, speaker_list, speaker_items)
            
        except Exception as e:
            self.device_error.emit(f"Failed to query audio devices: {e}")
    
    def get_device_info(self, device_id: int):
        """Get device information for a specific device ID."""
        try:
            return sd.query_devices(device_id)
        except Exception as e:
            self.device_error.emit(f"Failed to get device info: {e}")
            return None
    
    def get_device_ids(self):
        """Return list of available device IDs."""
        return self._device_ids
    
    def get_default_host_id(self):
        """Return the auto-selected host device ID, or None."""
        return self._default_host_id
    
    def get_default_speaker_index(self):
        """Return the auto-selected speaker combo index, or None."""
        return self._default_speaker_index
    
    def has_devices(self):
        """Check if any input devices are available."""
        return len(self._device_ids) > 0
