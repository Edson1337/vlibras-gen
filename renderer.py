#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# renderer.py — derived from VLibras (https://github.com/spbgovbr-vlibras)
# Original work © LAVID/UFPB, licensed under LGPLv3
# Modifications: changed output queue from "libras" to "libras-bridge"
#   to prevent round-robin with mixer.py and ensure exclusive consumption
#   by the bridge service.

import json
import logging
import os
import pika
import PikaManager
import signal
import socket
import subprocess

from operator import itemgetter
from pyvirtualdisplay import Display
from thread import start_new_thread
from time import sleep

#Temporary
from shutil import rmtree

#Temporary
def make_dir_if_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

# Logging configuration.
logger = logging.getLogger('renderer')
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler('/home/vlibras/log/renderer.log')
fh.setLevel(logging.DEBUG)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)

logger.addHandler(fh)
logger.addHandler(ch)

# Manager of queues connections.
#manager = PikaManager.PikaManager("150.165.205.10", "test", "test")

manager = PikaManager.PikaManager("rabbit")

TCP_IP = '0.0.0.0'
TCP_PORT = 5555

PATH_LIBRAS = os.getenv("VLIBRAS_VIDEO_LIBRAS")
VIDEO_CREATOR = os.getenv("VLIBRAS_VIDEO_CREATOR")
PATH_SCREENS = os.getenv("VLIBRAS_VIDEO_SCREENS")

#Create Paths if needed
make_dir_if_exists(PATH_LIBRAS)
make_dir_if_exists(VIDEO_CREATOR)
make_dir_if_exists(PATH_SCREENS)

# Status of renderer to process new requests. Answer one request at a time.
worker_available = True
# Identification to indicate the request being processed.
correlation_id = None
# Array that stores gloss and pts in json format to be sent to videoCreator.
gloss_buffer = []
# pyvirtualdisplay instance
display = None
# ffmpeg process instance
ffmpeg = None

def start_video_creator(id):
    """
    Start video creator server.

    Parameters
    ----------
    id : string
        Identification of request.
    """
    global display, ffmpeg
    logger.info("Starting video creator server")
    display = Display(visible=0, size=(800,600))
    display.start()
    subprocess.call(
        [
            VIDEO_CREATOR,
            id,
            "0",
            "30",
            "20",
            "25",
            "-screen-fullscreen", "1",
            "-screen-quality", "Fantastic",
            "-force-opengl"
        ],
        shell=False
    )
    ffmpeg.send_signal(signal.SIGQUIT)
    ffmpeg.communicate()
    display.stop()

def start_ffmpeg(id):
    """
    Start FFmpeg to capture the video creator display.

    Parameters
    ----------
    id : string
        Identification of request.
    """
    global ffmpeg, display
    logger.info("Starting ffmpeg")
    libras_video = os.path.join(PATH_LIBRAS, id + ".mp4")
    ffmpeg = subprocess.Popen(
        [
            "ffmpeg",
            "-y",
            "-loglevel", "quiet",
            "-video_size", "800x600",
            "-r", "30",
            "-f", "x11grab",
            "-draw_mouse", "0",
            "-i", str(display.cmd_param[-1]) + ".0+nomouse",
            "-vcodec", "libx264",
            "-pix_fmt", "yuv420p",
            "-an",
            libras_video
        ],
        shell=False
    )

def open_socket_connection():
    """
    Create a new socket TCP connection with video creator server.

    Returns
    -------
    socket object
        Connection with video creator server.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    logger.info("Opening connection with video creator")
    while True:
        try:
            s.connect((TCP_IP, TCP_PORT))
            break
        except:
            sleep(2)
    return s

def send_to_video_creator(id):
    # Stablishes connection with video creator server.
    socket = open_socket_connection()
    # Sort buffer to restore the original sequence.
    sorted_buffer = sorted(gloss_buffer, key=itemgetter("index"))
    logger.info("Sending gloss to video creator")
    for content in sorted_buffer:
        try:
            # Send gloss to video creator.
            socket.send(content["gloss"].encode("utf-8")+"#"+str(content["pts"]))
        except KeyError:
            logger.info("Sending control message to video creator")
            socket.send(content["control-message"].encode("utf-8")+"#"+str(content["pts"]))
            # Start ffmpeg to capture the video creator display.
            logger.info("Rendering video")
            start_ffmpeg(id)
        # sleep for 500 milliseconds
        sleep(.500)
    socket.close()
    del gloss_buffer[:]

def run(ch, method, properties, body):
    """
    Execute the worker.

    Parameters
    ----------
    ch : object
        Channel of communication.
    method : function
        Callback method.
    properties : object
        Message containing a set of 14 properties.
    body : string
        Json string containing the necessary arguments for workers.
    """
    global worker_available, correlation_id
    body = json.loads(body)
    # Check if worker is available to process a new request.
    if worker_available:
        logger.info("Processing request " + properties.correlation_id.encode("utf-8"))
        # Accept only messages with index equals to 1.
        try:
            if body["index"] == 1:
                # Change the status of renderer to occupied.
                worker_available = False
                # Stores the id of request in process.
                correlation_id = properties.correlation_id.encode("utf-8")
                # Stores the first gloss in the buffer.
                gloss_buffer.append(body)
            else:
                ch.basic_reject(delivery_tag=method.delivery_tag, requeue=True)
        except KeyError:
            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=True)
    # Else the worker is alread processing a request.
    else:
        # Check if the id of message match with the id of request being processed.
        if properties.correlation_id.encode("utf-8") == correlation_id:
            # Check if the body contains the control-message.
            try:
                if body["control-message"] == "FINALIZE":
                    # Get the total number of gloss of the current request.
                    total = body["index"] # Index of "FINALIZE" is the total number of gloss.
                    # Check if the buffer contains the correct number of gloss.
                    if len(gloss_buffer) == total - 1:
                        gloss_buffer.append(body)
                        logger.info("Preparing to generate the video")
                        start_new_thread(send_to_video_creator, (correlation_id,))
                        start_video_creator(correlation_id)
                        #Temporary
                        clean(correlation_id)
                        # Add path of libras video on body.
                        body["libras-video"] = os.path.join(PATH_LIBRAS, correlation_id + ".mp4")
                        worker_available = True
                        correlation_id = None
                        logger.info("Sending libras video to the libras queue")
                        manager.send_to_queue("libras-bridge", body, properties)
                        print ("OK")
                    else:
                        ch.basic_reject(delivery_tag=method.delivery_tag, requeue=True)
            except KeyError:
                # Control message doesn't exist, continues to store gloss.
                gloss_buffer.append(body)
        else:
            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=True)

#Temporary
def clean(id):
	logger.info("Cleaning screens files")
	path = os.path.join(PATH_SCREENS, id)
	rmtree(path, ignore_errors=True)

def keep_alive(conn_send, conn_receive):
	"""
    Keep the connection alive.

    Parameters
    ----------
    conn_send : object
        Connection of writer.
    conn_receive : object
        Connection of receiver.
    """
	while  True:
		sleep(30)
		try:
			conn_send.process_data_events()
			conn_receive.process_data_events()
		except:
			continue

start_new_thread(keep_alive, (manager.get_conn_send(), manager.get_conn_receive()))

print("Renderer listening...")
while True:
	try:
		manager.receive_from_queue("translations", run)
	except KeyboardInterrupt:
		manager.close_connections()
		os._exit(0)