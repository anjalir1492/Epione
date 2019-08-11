
import logging
import logging.handlers
import argparse
import sys
import os
import time
#import imutils

from bluetooth import *
from picamera.array import PiRGBArray
from picamera import PiCamera
from skimage.measure import compare_ssim
import time
import cv2
import uuid
from filestack import Client


#----------------------------------------------------------------------------------------------------------------
# raspbitsrvc.py - Support function for Epione colorimetry testing mobile app
# Executes as a service on a Raspberry Pi 3+ B
#
# April 20th '19, Gitanjali Rao, anjalir1492@gmail.com
#-------------------------------------------------------------------------------------------------------------------

fileName = 'colorimetry_test_sample_'+str(uuid.uuid4())+'.png'   #unique filename

class LoggerHelper(object):
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level

    def write(self, message):
        if message.rstrip() != "":
            self.logger.log(self.level, message.rstrip())


def setup_logging():
    # Default logging settings
    LOG_FILE = "/var/log/raspibtsrv.log"
    LOG_LEVEL = logging.INFO

    # Define and parse command line arguments
    argp = argparse.ArgumentParser(description="Anjali's Raspberry PI Bluetooth Server")
    argp.add_argument("-l", "--log", help="log (default '" + LOG_FILE + "')")

    # Grab the log file from arguments
    args = argp.parse_args()
    if args.log:
        LOG_FILE = args.log

    # Setup the logger
    logger = logging.getLogger(__name__)
    # Set the log level
    logger.setLevel(LOG_LEVEL)
    # Make a rolling event log that resets at midnight and backs-up every 3 days
    handler = logging.handlers.TimedRotatingFileHandler(LOG_FILE,
        when="midnight",
        backupCount=3)

    # Log messages should include time stamp and log level
    formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
    # Attach the formatter to the handler
    handler.setFormatter(formatter)
    # Attach the handler to the logger
    logger.addHandler(handler)

    # Replace stdout with logging to file at INFO level
    sys.stdout = LoggerHelper(logger, logging.INFO)
    # Replace stderr with logging to file at ERROR level
    sys.stderr = LoggerHelper(logger, logging.ERROR)

# take picture
def takePic(camera):
    # grab a reference to the raw camera capture. Camera init earlier
    rawCapture = PiRGBArray(camera)
    
    # allow the camera to warmup
    time.sleep(0.1)
    
    # grab an image from the camera
    camera.capture(rawCapture, format="bgr")
    image = rawCapture.array
    
    # crop image for Region of Interest - (x,y) is left top index, (x+w, y+h) is bottom right index
    # syntax flips to [y,x]
    # coordinates fixed based on fixed distance of fluid sample cuvette and standard lighting
    crop_img = image[160:360, 800:1000]

    # resize images to standard size (135x135 pixels) required by SSIM comparison
    dim = (135,135)
    resized_img = cv2.resize(crop_img, dim, interpolation = cv2.INTER_AREA)
    
    # write to file in working directory
    cv2.imwrite(fileName,resized_img)
    print("Picture taken, image saved")
    

# analyze image with set of control images, sort by highest ssim value and return matching control image number
def analyzeImage():
    # load the test image
    imageA = cv2.imread(fileName)
    
    # load all other control images
    imageL1 = cv2.imread("/home/pi/.virtualenvs/cv/colorimetry_sample_l1.png")
    imageL2 = cv2.imread("/home/pi/.virtualenvs/cv/colorimetry_sample_l2.png")
    imageL3 = cv2.imread("/home/pi/.virtualenvs/cv/colorimetry_sample_l3.png")
    imageL4 = cv2.imread("/home/pi/.virtualenvs/cv/colorimetry_sample_l4.png")
    imageL5 = cv2.imread("/home/pi/.virtualenvs/cv/colorimetry_sample_l5.png")
 
    # convert the images to grayscale
    grayA = cv2.cvtColor(imageA, cv2.COLOR_BGR2GRAY)
    grayL1 = cv2.cvtColor(imageL1, cv2.COLOR_BGR2GRAY)
    grayL2 = cv2.cvtColor(imageL2, cv2.COLOR_BGR2GRAY)
    grayL3 = cv2.cvtColor(imageL3, cv2.COLOR_BGR2GRAY)
    grayL4 = cv2.cvtColor(imageL4, cv2.COLOR_BGR2GRAY)
    grayL5 = cv2.cvtColor(imageL5, cv2.COLOR_BGR2GRAY)

    # compute the Structural Similarity Index (SSIM) between the two
    # images, ensuring that the difference image is returned
    # alternate approach is to use BGR2HSV and then compare color in range
    
    # initialize dictionery to store score:level
    myDict = {}
    # Test for levels starting with Level1
    (score, diff) = compare_ssim(grayA, grayL1, full=True)
    diff = (diff * 255).astype("uint8")
    myDict[score]="1"
    
    (score, diff) = compare_ssim(grayA, grayL2, full=True)
    myDict[score]="2"
    
    (score, diff) = compare_ssim(grayA, grayL3, full=True)
    myDict[score]="3"
    
    (score, diff) = compare_ssim(grayA, grayL4, full=True)
    myDict[score]="4"
    
    (score, diff) = compare_ssim(grayA, grayL5, full=True)
    myDict[score]="5"
    
    
    # sort on keys to get the largest score. Value corresponding to it will be the level that is
    # closest to the test sample
    
    myList = sorted(myDict)
    levelVal = myDict[myList[4]]  # [4] corresponds to the 5 element, the largest in the sorted list
    
    print("SSIM: {}".format(myList[4]))
    print("Level Value", levelVal)
    
    return levelVal

# Main loop
def main():
    # Setup logging
    setup_logging()

    # We need to wait until Bluetooth init is done
    time.sleep(10)

    # Make device visible
    os.system("hciconfig hci0 piscan")

    # Create a new server socket using RFCOMM protocol
    server_sock = BluetoothSocket(RFCOMM)
    # Bind to any port
    server_sock.bind(("", PORT_ANY))
    # Start listening
    server_sock.listen(1)

    # Get the port the server socket is listening
    port = server_sock.getsockname()[1]

    # The service UUID to advertise
    uuid = "7be1fcb3-5776-42fb-91fd-2ee7b5bbb86d"

    # Start advertising the service
    advertise_service(server_sock, "RaspiBtSrv",
                       service_id=uuid,
                       service_classes=[uuid, SERIAL_PORT_CLASS],
                       profiles=[SERIAL_PORT_PROFILE])
    
    # initialize camera. Resource intesnive activity, done once
    camera = PiCamera()


    # These are the operations the service supports
    # Feel free to add more
    operations = ["click", "sendthyresult", "analyze"]

    # Main Bluetooth server loop
    while True:

        print ("Waiting for connection on RFCOMM channel %d" % port)

        try:
            client_sock = None

            # This will block until we get a new connection
            client_sock, client_info = server_sock.accept()
            print ("Accepted connection from ", client_info)

            # Read the data sent by the client
            data = client_sock.recv(1024).decode('UTF-8')
            if len(data) == 0:
                break

            print ("Received [%s]" % data)

            # Handle the request

            if data == "click":
                # Take picture
                takePic(camera)
                # push image to web store
                client = Client("A5xYmgW3QRTSLGbWotlWVz")
                params = {"mimetype": "image/png"}
                filePath = '/home/pi/'+ fileName
                new_filelink = client.upload(filepath=filePath, store_params=params)  
                #new_filelink =  "https://cdn.filestackcontent.com/mV8ZhaR4Rlm3N2wE38gn" # uncomment for testing
                # print URL
                print("Taken, URL is"+new_filelink.url)
                #client_sock.send(new_filelink.url)
                response = new_filelink.url  
            elif data == "sendthyresult":
                # return captured image
                response = new_filelink.url 
            elif data == "analyze":
                # analyze images for colorimetry testing
                # call function that compares images, sorts and returns the level of addiction
                response = analyzeImage()
            # Insert more here
            elif data == "something":
                response = "msg:Report"
            # Insert more here
            else:
                # Unsupported params and actions 
                response = "msg:Not supported"
                
            client_sock.send(response)
            #Debug output
            print ("Sent back [%s]" % response)

        except IOError:
            pass

        except KeyboardInterrupt:

            if client_sock is not None:
                client_sock.close()

            server_sock.close()

            print ("Server going down")
            break

main()
