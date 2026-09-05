from db import init_db
from provisioning import worker_loop

if __name__ == "__main__":
    init_db()
    worker_loop(interval=30)
