#!/usr/bin/env python
"""
Raspberry Pi Photo Booth

This code is intended to be runs on a Raspberry Pi.
Currently both Python 2 and Python 3 are supported.

You can modify the config via [camera-config.yaml].
(The 1st time the code is run [camera-config.yaml] will be created based on [camera-config.example.yaml].
"""
__author__ = 'Jibbius (Jack Barker) - modified by Mathias Boulanger'
__version__ = '2.3'


#Standard imports
from time import sleep
from shutil import copy2
import sys
import datetime
import os

#Need to do this early, in case import below fails:
REAL_PATH = os.path.dirname(os.path.realpath(__file__))

#Additional Imports
try:
    from PIL import Image
    from ruamel import yaml
    import picamera
    import RPi.GPIO as GPIO

except ImportError as missing_module:
    print('--------------------------------------------')
    print('ERROR:')
    print(missing_module)
    print('')
    print(' - Please run the following command(s) to resolve:')
    if sys.version_info < (3,0):
        print('   pip install -r ' + REAL_PATH + '/requirements.txt')
    else:
        print('   python3 -m pip install -r ' + REAL_PATH + '/requirements.txt')
    print('')
    sys.exit()

#############################
### Load config from file ###
#############################
PATH_TO_CONFIG = REAL_PATH + '/camera-config.yaml'
PATH_TO_CONFIG_EXAMPLE = REAL_PATH + '/camera-config.example.yaml'

#Check if config file exists
if not os.path.exists(PATH_TO_CONFIG):
    #Create a new config file, using the example file
    print('Config file was not found. Creating:' + PATH_TO_CONFIG)
    copy2(PATH_TO_CONFIG_EXAMPLE, PATH_TO_CONFIG)

#Read config file using YAML interpreter
with open(PATH_TO_CONFIG, 'r') as stream:
    CONFIG = {}
    try:
        CONFIG = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        print(exc)

#Required config
try:
    CAMERA_BUTTON_PIN = CONFIG['CAMERA_BUTTON_PIN']
    EXIT_BUTTON_PIN = CONFIG['EXIT_BUTTON_PIN']
    FLASH_PIN = CONFIG['FLASH_PIN']
    TOTAL_PICS = CONFIG['TOTAL_PICS']
    PREP_DELAY = CONFIG['PREP_DELAY']
    COUNTDOWN = CONFIG['COUNTDOWN']
    PHOTO_W = CONFIG['PHOTO_W']
    PHOTO_H = CONFIG['PHOTO_H']
    SCREEN_W = CONFIG['SCREEN_W']
    SCREEN_H = CONFIG['SCREEN_H']
    CAMERA_ROTATION = CONFIG['CAMERA_ROTATION']
    CAMERA_HFLIP = CONFIG['CAMERA_HFLIP']
    DEBOUNCE_TIME = CONFIG['DEBOUNCE_TIME']
    TESTMODE_AUTOPRESS_BUTTON = CONFIG['TESTMODE_AUTOPRESS_BUTTON']
    TESTMODE_FAST = CONFIG['TESTMODE_FAST']
    SAVE_RAW_IMAGES_FOLDER = CONFIG['SAVE_RAW_IMAGES_FOLDER']
    PRINTER_MODE = CONFIG["PRINTER_MODE"]
    FLASH_MODE = CONFIG["FLASH_MODE"]

except KeyError as exc:
    print('')
    print('ERROR:')
    print(' - Problems exist within configuration file: [' + PATH_TO_CONFIG + '].')
    print(' - The expected configuration item ' + str(exc) + ' was not found.')
    print(' - Please refer to the example file [' + PATH_TO_CONFIG_EXAMPLE + '], for reference.')
    print('')
    sys.exit()

#TESTMODE config
if TESTMODE_FAST:
    TOTAL_PICS = 2
    PREP_DELAY = 2
    COUNTDOWN = 3

#Optional config
COPY_IMAGES_TO = []
try:
    if isinstance(CONFIG["COPY_IMAGES_TO"], list):
        COPY_IMAGES_TO.extend( CONFIG["COPY_IMAGES_TO"] )
    else:
        COPY_IMAGES_TO.append( CONFIG["COPY_IMAGES_TO"] )

except KeyError as exc:
    pass

##############################
### Setup Objects and Pins ###
##############################
#Setup GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(CAMERA_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(EXIT_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(FLASH_PIN , GPIO.OUT)

#Setup Camera
CAMERA = picamera.PiCamera()
CAMERA.rotation = CAMERA_ROTATION
CAMERA.annotate_text_size = 160
CAMERA.resolution = (PHOTO_W, PHOTO_H)
CAMERA.hflip = CAMERA_HFLIP

########################
### Helper Functions ###
########################
def health_test_required_folders():
    folders_list=[SAVE_RAW_IMAGES_FOLDER]
    folders_list.extend(COPY_IMAGES_TO)
    folders_checked=[]

    for folder in folders_list:
        if folder not in folders_checked:
            folders_checked.append(folder)
        else:
            print('ERROR: Cannot use same folder path ('+folder+') twice. Refer config file.')

        #Create folder if doesn't exist
        if not os.path.exists(folder):
            print('Creating folder: ' + folder)
            os.makedirs(folder)

def print_overlay(string_to_print):
    """
    Writes a string to both [i] the console, and [ii] CAMERA.annotate_text
    """
    print(string_to_print)
    CAMERA.annotate_text = string_to_print

def get_base_filename_for_images():
    """
    For each photo-capture cycle, a common base filename shall be used,
    based on the current timestamp.

    Example:
    ${ProjectRoot}/photos/2017-12-31_23-59-59

    The example above, will later result in:
    ${ProjectRoot}/photos/2017-12-31_23-59-59_1of4.png, being used as a filename.
    """

    base_filename = str(datetime.datetime.now()).split('.')[0]
    base_filename = base_filename.replace(' ', '_')
    base_filename = base_filename.replace(':', '-')

    base_filepath = REAL_PATH + '/' + SAVE_RAW_IMAGES_FOLDER + '/' + base_filename

    return base_filepath

def remove_overlay(overlay_id):
    """
    If there is an overlay, remove it
    """
    if overlay_id != -1:
        CAMERA.remove_overlay(overlay_id)

# overlay one image on screen
def overlay_image(image_path, duration=0, layer=3, mode='RGB'):
    """
    Add an overlay (and sleep for an optional duration).
    If sleep duration is not supplied, then overlay will need to be removed later.
    This function returns an overlay id, which can be used to remove_overlay(id).
    """

    # Load the (arbitrarily sized) image
    img = Image.open(image_path)

    if( img.size[0] > SCREEN_W):
        # To avoid memory issues associated with large images, we are going to resize image to match our screen's size:
        basewidth = SCREEN_W
        wpercent = (basewidth/float(img.size[0]))
        hsize = int((float(img.size[1])*float(wpercent)))
        img = img.resize((basewidth,hsize), Image.ANTIALIAS)

    # "
    #   The camera`s block size is 32x16 so any image data
    #   provided to a renderer must have a width which is a
    #   multiple of 32, and a height which is a multiple of
    #   16.
    # "
    # Refer:
    # http://picamera.readthedocs.io/en/release-1.10/recipes1.html#overlaying-images-on-the-preview

    # Create an image padded to the required size with mode 'RGB' / 'RGBA'
    pad = Image.new(mode, (
        ((img.size[0] + 31) // 32) * 32,
        ((img.size[1] + 15) // 16) * 16,
    ))

    # Paste the original image into the padded one
    pad.paste(img, (0, 0))

    #Get the padded image data
    try:
        padded_img_data = pad.tobytes()
    except AttributeError:
        padded_img_data = pad.tostring() # Note: tostring() is deprecated in PIL v3.x

    # Add the overlay with the padded image as the source,
    # but the original image's dimensions
    o_id = CAMERA.add_overlay(padded_img_data, size=img.size)
    o_id.layer = layer

    if duration > 0:
        sleep(duration)
        CAMERA.remove_overlay(o_id)
        o_id = -1 # '-1' indicates there is no overlay

    return o_id # if we have an overlay (o_id > 0), we will need to remove it later

###############
### Screens ###
###############
def prep_for_photo_screen(photo_number):
    """
    Prompt the user to get ready for the next photo
    """

    #Get ready for the next photo
    get_ready_image = REAL_PATH + '/assets/get_ready_' + str(photo_number) + '.png'
    overlay_image(get_ready_image, PREP_DELAY, 3, 'RGBA')

def taking_photo(photo_number, filename_prefix):
    """
    This function captures the photo
    """

    #get filename to use
    filename = filename_prefix + '_' + str(photo_number) + 'of'+ str(TOTAL_PICS)+'.jpg'

    #countdown from 3, and display countdown on screen
    for counter in range(COUNTDOWN, 0, -1):
        #print_overlay("             ..." + str(counter))
        print_overlay(str(counter))
        sleep(1)

    #Take still
    CAMERA.annotate_text = ''

    if FLASH_MODE:
        GPIO.output(FLASH_PIN, GPIO.HIGH)
        CAMERA.capture(filename)
        GPIO.output(FLASH_PIN, GPIO.LOW)
    else:
        CAMERA.capture(filename)
    
    print('Photo (' + str(photo_number) + ') saved: ' + filename)
    return filename

def playback_screen(filename_prefix):
    """
    Final screen before main loop restarts
    """

    #Processing
    print('Processing...')
    processing_image = REAL_PATH + '/assets/processing.png'
    prev_overlay = overlay_image(processing_image, False, (3 + TOTAL_PICS + 1))
    sleep(2)

    #Playback
    for photo_number in range(1, TOTAL_PICS + 1):
        filename = filename_prefix + '_' + str(photo_number) + 'of' + str(TOTAL_PICS) + '.jpg'
        
        #code to overlay number on pictures (too slow need to be improved...)
        #filename2 = REAL_PATH + '/assets/photo_num_' + str(photo_number) + '.png'
        #overlay_filename = '/tmp/playback_' + str(photo_number) + '.png'

        #the size of the 2 pictures needs to be the same... 
        #background = Image.open(filename).convert('RGBA').resize((1280,1024), Image.ANTIALIAS)
        #foreground = Image.open(filename2 ).convert('RGBA')
        #Image.alpha_composite(background, foreground).save(overlay_filename)

        this_overlay = overlay_image(filename, False, (3 + TOTAL_PICS + 1))

        remove_overlay(prev_overlay)
        sleep(2)
        prev_overlay = this_overlay

    remove_overlay(prev_overlay)

    #All done
    print('All done!')
    finished_image = REAL_PATH + '/assets/all_done.png'
    overlay_image(finished_image, 5)

def combine_images(filename_prefix):
    print("Processing images into combined strip")

    processing_image = REAL_PATH + "/assets/processing2.png"
    printing_overlay = overlay_image(processing_image)

    # Do the merging
    blankImage = Image.open(REAL_PATH + "/assets/blank.jpg")

    image1 = Image.open(filename_prefix + '_1of4.jpg')
    image1 = image1.resize((732,439))
    blankImage.paste(image1, (20,20))

    image2 = Image.open(filename_prefix + '_2of4.jpg')
    image2 = image2.resize((732,439))
    blankImage.paste(image2, (20,479))

    image3 = Image.open(filename_prefix + '_3of4.jpg')
    image3 = image3.resize((732,439))
    blankImage.paste(image3, (20,938))

    image4 = Image.open(filename_prefix + '_4of4.jpg')
    image4 = image4.resize((732,439))
    blankImage.paste(image4, (20,1397))

    blankImage.save(filename_prefix + '_combined.jpg', 'JPEG', quality=100)
    
    combinedImage = (filename_prefix + '_combined.jpg')

    print("Creating binary file for printer")
    os.system('brother_ql_create --dither --model QL-570 ' + combinedImage + ' > /tmp/' + combinedImage + '.bin')

    print("Sending file to printer")
    os.system('cat /tmp/' + combinedImage + '.bin > /dev/usb/lp0')

    print("Deleting binary file")
    os.system('rm -f /tmp/' + combinedImage + '.bin')

    remove_overlay(printing_overlay)

def main():
    """
    Main program loop
    """

    #Start Program
    print('Welcome to the Photobooth!')
    print('(version ' + __version__ + ')')
    print('')
    print('Press the \'Take photo\' button to take a photo')
    print('Use [Ctrl] + [\\] to exit')
    print('')

    #Setup any required folders (if missing)
    health_test_required_folders()

    #Display intro screen
    intro_image_1 = REAL_PATH + '/assets/intro_1.png'
    intro_image_2 = REAL_PATH + '/assets/intro_2.png'
    overlay_1 = overlay_image(intro_image_1, 0, 3)
    overlay_2 = overlay_image(intro_image_2, 0, 4)

    #Start camera preview
    CAMERA.start_preview(resolution=(SCREEN_W, SCREEN_H))

    #Wait for someone to push the button
    i = 0
    blink_speed = 10

   #Use falling edge detection to see if button is being pushed in
    GPIO.add_event_detect(CAMERA_BUTTON_PIN, GPIO.FALLING)
    GPIO.add_event_detect(EXIT_BUTTON_PIN, GPIO.FALLING)

    while True:
        photo_button_is_pressed = None
        exit_button_is_pressed = None

        if GPIO.event_detected(CAMERA_BUTTON_PIN):
            sleep(DEBOUNCE_TIME)
            if GPIO.input(CAMERA_BUTTON_PIN) == 0:
                photo_button_is_pressed = True

        if GPIO.event_detected(EXIT_BUTTON_PIN):
            sleep(DEBOUNCE_TIME)
            if GPIO.input(EXIT_BUTTON_PIN) == 0:
                exit_button_is_pressed = True

        if exit_button_is_pressed is not None:
            return #Exit the photo booth

        if TESTMODE_AUTOPRESS_BUTTON:
            photo_button_is_pressed = True

        #Stay inside loop, until button is pressed
        if photo_button_is_pressed is None:

            #After every 10 cycles, alternate the overlay
            i = i+1
            if i == blink_speed:
                overlay_2.alpha = 255
            elif i == (2 * blink_speed):
                overlay_2.alpha = 0
                i = 0
                #if random.randint(1,101) > 80:
                #flash()

            #Regardless, restart loop
            sleep(0.1)
            continue

        #Button has been pressed!
        print('Button pressed! You folks are in for a treat.')

        #Silence GPIO detection
        GPIO.remove_event_detect(CAMERA_BUTTON_PIN)
        GPIO.remove_event_detect(EXIT_BUTTON_PIN)

        #Get filenames for images
        filename_prefix = get_base_filename_for_images()
        remove_overlay(overlay_2)
        remove_overlay(overlay_1)

        photo_filenames = []
        for photo_number in range(1, TOTAL_PICS + 1):
            prep_for_photo_screen(photo_number)
            fname = taking_photo(photo_number, filename_prefix)
            photo_filenames.append(fname)

        #combine images into photo strip and print it
        if PRINTER_MODE:
			combine_images(filename_prefix)

        #thanks for playing
        playback_screen(filename_prefix)

        #Save photos into additional folders (for post-processing/backup... etc.)
        for dest in COPY_IMAGES_TO:
            for src in photo_filenames:
                print(src + ' -> ' + dest)
                copy2(src, dest)

        # If we were doing a test run, exit here.
        if TESTMODE_AUTOPRESS_BUTTON:
            break

        # Otherwise, display intro screen again
        overlay_1 = overlay_image(intro_image_1, 0, 3)
        overlay_2 = overlay_image(intro_image_2, 0, 4)
        GPIO.add_event_detect(CAMERA_BUTTON_PIN, GPIO.FALLING)
        GPIO.add_event_detect(EXIT_BUTTON_PIN, GPIO.FALLING)
        print('Press the button to take a photo')

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print('')
        print('Goodbye')
        print('')

    except Exception as exception:
        print("unexpected error: ", str(exception))

    finally:
        CAMERA.stop_preview()
        CAMERA.close()
        GPIO.cleanup()
        sys.exit()
