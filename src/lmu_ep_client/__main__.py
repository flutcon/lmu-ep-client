import logging

from lmu_ep_client.poller import run

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    run()
