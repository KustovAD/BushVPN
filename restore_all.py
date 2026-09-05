from db import init_db
from provisioning import sync_all_servers

if __name__ == "__main__":
    init_db()
    print("Rebuilding configs from templates and active users...")
    sync_all_servers(force=True)
    print("Done.")
