"""
PicoCalc filesystem cleanup - removes source directories that shadow C modules.
Copy this to the device and run: import cleanup
"""
import os

def rmtree(path):
    try:
        for f in os.listdir(path):
            fp = path + '/' + f
            try:
                os.remove(fp)
            except:
                rmtree(fp)
        os.rmdir(path)
        print("Removed:", path)
    except:
        print("Not found:", path)

# Source directories that shadow the firmware C modules
rmtree('/picocalcdisplay')
rmtree('/vtterminal')
rmtree('/Client_Code')

# Stale file on root (module version is in /modules/)
try:
    os.remove('/sd_chk.py')
    print("Removed: /sd_chk.py")
except:
    pass

# Self-delete
try:
    os.remove('/cleanup.py')
    print("Removed: /cleanup.py")
except:
    pass

print("\nRemaining files:")
print(os.listdir('/'))
print("\nDone! Power cycle the device.")
