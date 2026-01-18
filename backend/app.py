from .server import create_app, RuntimeState
from .config import load_config
from .sensors import SensorManager


config = load_config()
sensors = SensorManager(config)
state = RuntimeState(config=config, sensors=sensors)
app = create_app(state)
