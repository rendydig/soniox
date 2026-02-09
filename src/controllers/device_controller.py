import sounddevice as sd
from PySide6.QtCore import QObject, Signal


class DeviceController(QObject):
    """Handles audio device management and selection."""
    
    device_error = Signal(str)
    devices_populated = Signal(list, list)
    
    def __init__(self):
        super().__init__()
        self._device_ids = []
    
    def populate_devices(self):
        """Query and populate available audio input devices."""
        try:
            devs = sd.query_devices()
            device_list = []
            device_ids = []
            
            for idx, d in enumerate(devs):
                if d.get('max_input_channels', 0) > 0:
                    name = d.get('name', f'Device {idx}')
                    sr = d.get('default_samplerate') or 44100
                    label = f"[{idx}] {name} — {int(sr)} Hz"
                    device_list.append(label)
                    device_ids.append(idx)
            
            self._device_ids = device_ids
            self.devices_populated.emit(device_list, device_ids)
            
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
    
    def has_devices(self):
        """Check if any input devices are available."""
        return len(self._device_ids) > 0
