"""
Enhanced SD card initialization module for PicoCalc
Specifically configured for the hardware with:
- SPI0_CS  = GPIO 17
- SPI0_TX  = GPIO 19 (MOSI)
- SPI0_SCK = GPIO 18
- SPI0_RX  = GPIO 16 (MISO)
"""

import machine
import os
import time
import gc

def initsd(debug=True):
    """
    Initialize and mount the SD card with the correct pins for your hardware
    
    Args:
        debug: Whether to print debug information
    
    Returns:
        SD card object if successful, None otherwise
    """
    if debug:
        print("Initializing SD card...")
    
    try:
        # Import the SD card module
        import sdcard
        
        # Define pins for SPI0 based on the schematic
        spi = machine.SPI(0,
                         baudrate=1000000,
                         polarity=0,
                         phase=0,
                         bits=8,
                         firstbit=machine.SPI.MSB,
                         sck=machine.Pin(18),    # SPI0_SCK
                         mosi=machine.Pin(19),   # SPI0_TX
                         miso=machine.Pin(16))   # SPI0_RX
        
        # Initialize CS pin - GPIO 17
        cs = machine.Pin(17, machine.Pin.OUT)
        
        # Make sure CS is high before starting (deselected)
        cs.value(1)
        time.sleep_ms(100)
        
        # Try to unmount if already mounted
        try:
            os.umount('/sd')
            if debug:
                print("Unmounted existing /sd")
        except:
            pass
        
        # Initialize the SD card
        if debug:
            print("Creating SD card object...")
        sd = sdcard.SDCard(spi, cs)
        
        if debug:
            print("Mounting SD card to /sd...")
        
        # Mount the SD card
        os.mount(sd, '/sd')
        
        # Create py_scripts directory if it doesn't exist
        try:
            os.listdir('/sd/py_scripts')
            if debug:
                print("py_scripts directory exists")
        except:
            if debug:
                print("Creating py_scripts directory")
            try:
                os.mkdir('/sd/py_scripts')
            except:
                if debug:
                    print("Could not create py_scripts directory")
        
        # Get and display storage information
        if debug:
            try:
                stat = os.statvfs('/sd')
                block_size = stat[0]
                total_blocks = stat[2]
                free_blocks = stat[3]
                
                total_bytes = block_size * total_blocks
                free_bytes = block_size * free_blocks
                
                if total_bytes > 1024*1024*1024:
                    print(f"SD card: {total_bytes/(1024*1024*1024):.1f} GB total, "
                          f"{free_bytes/(1024*1024*1024):.1f} GB free")
                else:
                    print(f"SD card: {total_bytes/(1024*1024):.1f} MB total, "
                          f"{free_bytes/(1024*1024):.1f} MB free")
            except Exception as e:
                print(f"SD card mounted but couldn't get size info: {e}")
        
        # Run garbage collection to free memory
        gc.collect()
        
        return sd
            
    except ImportError as e:
        if debug:
            print(f"sdcard module not found: {e}")
        return None
    except Exception as e:
        if debug:
            print(f"SD initialization error: {e}")
        return None

def killsd():
    """Unmount the SD card"""
    try:
        os.umount('/sd')
        return True
    except:
        return False

def check_real_sd():
    """Check if the SD card is correctly mounted with its full capacity"""
    try:
        # Get storage info
        stat = os.statvfs('/sd')
        block_size = stat[0]
        total_blocks = stat[2]
        
        # Calculate total size in bytes
        total_bytes = block_size * total_blocks
        
        # Convert to MB for easier comparison
        total_mb = total_bytes / (1024 * 1024)
        
        # If it's less than 100MB, it's probably not a real SD card mount
        # but just a directory on the internal flash
        if total_mb < 100:
            print(f"WARNING: SD card shows only {total_mb:.2f} MB")
            print("This may indicate that the SD card is not properly mounted")
            print("Make sure your SD card is properly connected")
            return False
        else:
            print(f"SD card correctly mounted with {total_mb:.2f} MB capacity")
            return True
    except Exception as e:
        print(f"Error checking SD card: {e}")
        return False

def format_size(size_bytes):
    """Format a size in bytes to a human-readable string"""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes} bytes"

def show_sd_info():
    """Display detailed information about the SD card"""
    try:
        # Get storage info
        stat = os.statvfs('/sd')
        block_size = stat[0]
        total_blocks = stat[2]
        free_blocks = stat[3]
        
        total_bytes = block_size * total_blocks
        free_bytes = block_size * free_blocks
        used_bytes = total_bytes - free_bytes
        
        print("\n=== SD Card Information ===")
        print(f"Total space: {format_size(total_bytes)}")
        print(f"Used space: {format_size(used_bytes)}")
        print(f"Free space: {format_size(free_bytes)}")
        print(f"Usage: {(used_bytes / total_bytes) * 100:.1f}%")
        
        # List root directory
        print("\nRoot directory contents:")
        contents = os.listdir('/sd')
        
        # Show directories first
        dirs = []
        files = []
        
        for item in contents:
            try:
                stat = os.stat(f'/sd/{item}')
                is_dir = stat[0] & 0x4000
                
                if is_dir:
                    dirs.append(item)
                else:
                    files.append((item, stat[6]))  # (name, size)
            except:
                files.append((item, 0))
        
        # Print directories
        for d in sorted(dirs):
            print(f"   {d}/")
        
        # Print files (limit to first 10)
        for name, size in sorted(files)[:10]:
            print(f"   {name} ({format_size(size)})")
        
        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more files")
            
        # Show py_scripts if it exists
        try:
            py_files = os.listdir('/sd/py_scripts')
            if py_files:
                print("\npy_scripts directory:")
                for py in sorted(py_files):
                    try:
                        stat = os.stat(f'/sd/py_scripts/{py}')
                        size = stat[6]
                        print(f"   {py} ({format_size(size)})")
                    except:
                        print(f"   {py}")
        except:
            pass
            
        return True
    except Exception as e:
        print(f"Error getting SD card info: {e}")
        return False

# Run a basic test if this module is executed directly
if __name__ == "__main__":
    print("Testing SD card initialization...")
    sd = initsd()
    if sd:
        print("SD card initialization successful!")
        show_sd_info()
    else:
        print("SD card initialization failed!")