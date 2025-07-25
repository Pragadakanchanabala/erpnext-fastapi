import socket

def is_internet_connected(host="8.8.8.8", port=53, timeout=3) -> bool:
    """
    Check internet connectivity by attempting to connect to a public DNS server (Google).
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False
