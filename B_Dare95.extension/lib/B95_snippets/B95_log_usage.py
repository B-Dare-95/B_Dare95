def B95_log_usage():
    import getpass
    import socket
    import datetime
    import os

    # Path to shared log file on server (UNC path or mapped drive)
    log_file = r"Y:\Architectural Public\Mohamed Bedair_AR\B-Dare_SDC\script_usage.log"  # Replace this with your actual path

    # Gather logging info
    try:
        username = getpass.getuser()
    except:
        username = "UnknownUser"

    try:
        hostname = socket.gethostname()
    except:
        hostname = "UnknownHost"

    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except:
        timestamp = "UnknownTime"

    try:
        script_name = os.path.basename(__file__)
    except:
        script_name = "UnknownScript"

    # Write log entry
    try:
        with open(log_file, "a") as f:
            f.write("{0}, {1}, {2}, {3}\n".format(timestamp, username, hostname, script_name))
    except:
        pass  # Do not interrupt script execution if logging fails