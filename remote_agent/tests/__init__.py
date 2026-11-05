import logging

# Keep expected reconnect warnings out of the test output.
logging.getLogger("nova_agent").addHandler(logging.NullHandler())
logging.getLogger("nova_agent").propagate = False
