from hx711 import HX711
from machine import freq
import network
from umqtt.robust import MQTTClient
from time import sleep
import json
import math
import secrets

###############################################################################################################
# Config variables
################################################################################################################
sensorName = "water_bowl_sensor"            # name of the sensor (this is how the sensor will show up in Home Assistant)
sensorFriendlyName = "Water bowl sensor"    # friendly name of sensor to be shown in Home Assistant
updateInterval = 5 * 60                     # how often the sensor reports to the MQTT server (in seconds)
loadCellZeroValue = -81500                  # load cell specific zero value (what does your load cell read with zero weight on it?)
loadCellScalingFactor = 227                 # scaling factor to convert numeric value read from load cell to grams
emptyBowlWeight = 1140                      # how many grams does the empty water bowl weigh?

# set clock freq to 160 MHz -- enables proper readings from hx711 chip
#freq(160000000)

###############################################################################################################
# WiFi setup
################################################################################################################
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
def connectToWiFi():
    if wlan.isconnected():
        return True
    print("Connecting to WiFi")
    wlan.connect(secrets.wifiSSID, secrets.wifiPassword)
    sleep(30)
    maxConnectionAttempts = 10
    timeBetweenConnectionAttempts = 60
    connectionAttemptNumber = 1
    while not wlan.isconnected() and connectionAttemptNumber <= maxConnectionAttempts:
        print("Failed to connect to WiFi...trying again in " + str(timeBetweenConnectionAttempts) + " seconds (reconnection attempt " + str(connectionAttemptNumber) + ")")
        wlan.connect(secrets.wifiSSID, secrets.wifiPassword)
        connectionAttemptNumber += 1
        sleep(timeBetweenConnectionAttempts)
    if wlan.isconnected():
        status = wlan.ifconfig()
        print('Connected to WiFi with IP: ' + status[0])
        return True
    else:
        print("Failed to connect to WiFi after " + str(maxConnectionAttempts) + " tries")
        return False
connectToWiFi()

###############################################################################################################
# MQTT setup
################################################################################################################
stateTopic = "homeassistant/" + sensorName + "/state"
config = {
    "name" : sensorFriendlyName,
    "state_topic": stateTopic,
    "value_template": "{{ value_json.waterLevel }}"
}
# MQTT callback (for handling messages received -- not currently used for anything)
def onMQTTMessage(topic, msg, retain, dup):
    print('MQTT message received on topic ' + topic + ' message: ' + msg)
# connect MQTT
mqttClient = MQTTClient(sensorName, secrets.mqttServerAddress, user=secrets.mqttUsername, password=secrets.mqttPassword)
mqttClient.set_callback(onMQTTMessage)
mqttIsConnected = False
def connectToMQTT():
    if not mqttIsConnected:
        print("Connecting to MQTT server at " + secrets.mqttServerAddress)
        mqttClient.connect()
    else:
        mqttClient.ping()
    maxConnectionAttempts = 10
    timeBetweenConnectionAttempts = 60
    connectionAttemptNumber = 1
    while mqttClient.is_conn_issue() and connectionAttemptNumber <= maxConnectionAttempts:
        print("Failed to connect to MQTT server...trying again in " + str(timeBetweenConnectionAttempts) + " seconds (reconnection attempt " + str(connectionAttemptNumber) + ")")
        mqttClient.reconnect()
        connectionAttemptNumber += 1
        sleep(timeBetweenConnectionAttempts)
    if not mqttClient.is_conn_issue():
        if not mqttIsConnected:
            # MQTT discovery for home assistant
            mqttClient.publish("homeassistant/sensor/" + sensorName + "/config", json.dumps(config))
            # Subscribe to any desired topics
            # mqttClient.subscribe("/" + sensorName)
        else:
            mqttClient.resubscribe()
        return True
    else:
        print("Failed to connect to MQTT after " + str(maxConnectionAttempts) + " tries")
        return False
connectToMQTT()
mqttIsConnected = True

###############################################################################################################
# Load cell setup
################################################################################################################
loadCell = HX711(d_out=17, pd_sck=16)
loadCell.channel = HX711.CHANNEL_A_64

while(True):
    # read load cell and calculate water level in bowl
    scaledValue = (loadCell.read() - loadCellZeroValue) / loadCellScalingFactor
    waterLevel = math.floor((scaledValue - emptyBowlWeight) / 29.57) # an ounce of water weighs 29.57 grams
    print("Water level: " + str(waterLevel))
    # report water level to server
    if connectToWiFi() and connectToMQTT():
        mqttClient.publish(stateTopic, json.dumps({'waterLevel': waterLevel}))
    sleep(updateInterval)