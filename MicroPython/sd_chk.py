# SD Card Test Script
# This script tests SD card initialization with the correct pins
# for your specific hardware

import machine
import os
import time
import gc
import sys

print("\n==== SD CARD TEST SCRIPT ====\n")

# Check if sdcard module is available
try:
    time.sleep_ms(900)
    import sdcard
    time.sleep_ms(1900)
    print("[OK] sdcard module is available")
except ImportError:
    print("[X] sdcard module not found - please install it first")
    sys.exit(1)

# First, try to see what's currently at /sd
print("\nChecking current /sd status:")
try:
    contents = os.listdir("/sd")
    print(f"- /sd exists with {len(contents)} items")
    
    # Check if it's a real SD card or just a directory
    stat = os.statvfs("/sd")
    block_size = stat[0]
    total_blocks = stat[2]
    total_mb = (block_size * total_blocks) / (1024 * 1024)
    print(f"- Current reported size: {total_mb:.2f} MB")
    
    if total_mb < 5:
        print("[!] This appears to be just a directory, not a mounted SD card")
except:
    print("[X] /sd doesn't exist or can't be accessed")

# Try to unmount if already mounted
try:
    print("\nTrying to unmount existing /sd...")
    os.umount("/sd")
    print("[OK] Successfully unmounted")
except:
    print("[i] Nothing to unmount")

# Display memory before SD card initialization
gc.collect()
print(f"\nMemory before initialization: {gc.mem_free()} bytes free")

# Initialize SPI and SD card with the correct pins for your hardware
print("\nInitializing SD card with correct pins:")
print("- Using SPI0 (not SPI1)")
print("- SPI0_CS  = GPIO 17")
print("- SPI0_TX  = GPIO 19 (MOSI)")
print("- SPI0_SCK = GPIO 18")
print("- SPI0_RX  = GPIO 16 (MISO)")

try:
    # Initialize SPI0
    print("\nSetting up SPI0...")
    spi = machine.SPI(0,
                     baudrate=1000000,
                     polarity=0,
                     phase=0,
                     bits=8,
                     firstbit=machine.SPI.MSB,
                     sck=machine.Pin(18),
                     mosi=machine.Pin(19),
                     miso=machine.Pin(16))
    
    # Initialize CS pin
    print("Setting up CS pin (GPIO 17)...")
    cs = machine.Pin(17, machine.Pin.OUT)
    cs.value(1)  # Deselect initially
    time.sleep_ms(100)
    
    # Initialize SD card
    print("Creating SD card object...")
    sd = sdcard.SDCard(spi, cs)
    
    # Mount the SD card
    print("Mounting SD card to /sd...")
    os.mount(sd, "/sd")
    print("[OK] SD card mounted successfully!")
    
    # Check storage info
    print("\nChecking SD card capacity:")
    stat = os.statvfs("/sd")
    block_size = stat[0]
    total_blocks = stat[2]
    free_blocks = stat[3]
    
    total_bytes = block_size * total_blocks
    free_bytes = block_size * free_blocks
    used_bytes = total_bytes - free_bytes
    
    # Format for readability
    def format_size(size):
        if size >= 1024*1024*1024:
            return f"{size/(1024*1024*1024):.2f} GB"
        elif size >= 1024*1024:
            return f"{size/(1024*1024):.1f} MB"
        else:
            return f"{size/1024:.1f} KB"
    
    print(f"- Total space: {format_size(total_bytes)}")
    print(f"- Used space: {format_size(used_bytes)}")
    print(f"- Free space: {format_size(free_bytes)}")
    print(f"- Usage: {(used_bytes / total_bytes) * 100:.1f}%")
    
    # Check directory contents
    print("\nListing SD card contents:")
    contents = os.listdir("/sd")
    if len(contents) == 0:
        print("- SD card is empty")
    else:
        for item in contents[:10]:  # Show first 10 items
            try:
                item_stat = os.stat(f"/sd/{item}")
                is_dir = item_stat[0] & 0x4000
                size = item_stat[6]
                print(f"- {'' if is_dir else ''} {item}" + (f" ({size} bytes)" if not is_dir else ""))
            except:
                print(f"- [?] {item}")
    
    # Check if we can write to the card
    print("\nTesting write access:")
    try:
        with open("/sd/test.txt", "w") as f:
            f.write("This is a test file created by the SD card test script")
        print("[OK] Successfully wrote test file")
        
        # Read it back
        with open("/sd/test.txt", "r") as f:
            content = f.read()
        print(f"[OK] Successfully read back: {content[:20]}...")
        
        # Delete the test file
        os.remove("/sd/test.txt")
        print("[OK] Successfully deleted test file")
    except Exception as e:
        print(f"[X] Write test failed: {e}")
    
    print("\n==== SD CARD TEST COMPLETE ====")
    print("Your SD card is properly initialized and mounted!")
    print("The 32GB capacity should now be available at /sd")
    
except Exception as e:
    print(f"\n[X] SD card initialization failed: {e}")
    print("\nTroubleshooting tips:")
    print("1. Double-check that your SD card is properly inserted")
    print("2. Make sure the SD card is formatted as FAT32")
    print("3. Verify the wiring connections")
    print("4. Try a different SD card if available")
    
finally:
    # Display memory after SD card initialization
    gc.collect()
    print(f"\nMemory after test: {gc.mem_free()} bytes free")