from hx711 import HX711
import network
from umqtt.robust import MQTTClient
from time import sleep
import json
import math
import secrets

###############################################################################################################
# Config variables
###############################################################################################################
sensorName = "water_bowl_sensor"            # name of the sensor
sensorFriendlyName = "Water bowl sensor"    # friendly name of sensor to be shown in Home Assistant (this is how the sensor will be shown in the HA frontend)
loadCellZeroValue = -82420                  # load cell specific zero value (what does your load cell read with zero weight on it?) - raw value (not grams)
loadCellScalingFactor = 227                 # scaling factor to convert raw value read from load cell to grams
emptyBowlWeight = 1255                      # how many grams does the empty water bowl weigh?
reportingThreshold = 10                     # percentage difference in measurements to trigger a report to HomeAssistant

###############################################################################################################
# WiFi setup
###############################################################################################################
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
def connectToWiFi():
    if wlan.isconnected():
        status = wlan.ifconfig()
        print(f"Connected to WiFi with IP: {status[0]}")
        return True
    print("Connecting to WiFi")
    wlan.connect(secrets.wifiSSID, secrets.wifiPassword)
    maxConnectionAttempts = 10
    timeBetweenConnectionAttempts = 60
    connectionAttemptNumber = 1
    while not wlan.isconnected() and connectionAttemptNumber <= maxConnectionAttempts:
        print(f"Failed to connect to WiFi...trying again in {timeBetweenConnectionAttempts} seconds (reconnection attempt {connectionAttemptNumber})")
        wlan.connect(secrets.wifiSSID, secrets.wifiPassword)
        connectionAttemptNumber += 1
        sleep(timeBetweenConnectionAttempts)
    if wlan.isconnected():
        status = wlan.ifconfig()
        print(f"Connected to WiFi with IP: {status[0]}")
        return True
    else:
        print(f"Failed to connect to WiFi after {maxConnectionAttempts} tries")
        return False
connectToWiFi()

###############################################################################################################
# MQTT setup
###############################################################################################################
stateTopic = f"homeassistant/{sensorName}/state"
config = {
    "name" : sensorFriendlyName,
    "state_topic": stateTopic,
    "value_template": "{{ value_json.waterLevel }}",
    "unit_of_measurement": "ml",
    "icon": "mdi:water-outline"
}
mqttClient = MQTTClient(sensorName, secrets.mqttServerAddress, user=secrets.mqttUsername, password=secrets.mqttPassword) if secrets.mqttUsername != "" and secrets.mqttPassword != "" else MQTTClient(sensorName, secrets.mqttServerAddress)
# MQTT callback
def onMQTTMessage(topic, msg, retain, dup):
    print(f"MQTT message received on topic {topic} - message \"{msg}\"")
    if topic == b"homeassistant/status" and msg == b"online":
        print("Home assistant restarted...resending sensor value(s)")
        if connectToWiFi() and connectToMQTT():
            mqttClient.publish(stateTopic, json.dumps({'waterLevel': lastReportedWaterLevel}))
            print("Message sent to MQTT server")
# connect MQTT
mqttClient.set_callback(onMQTTMessage)
mqttInitialConnectionMade = False
def connectToMQTT():
    if not mqttInitialConnectionMade:
        print(f"Connecting to MQTT server at {secrets.mqttServerAddress}")
        mqttClient.connect()
    else:
        mqttClient.ping()
    maxConnectionAttempts = 10
    timeBetweenConnectionAttempts = 60
    connectionAttemptNumber = 1
    while mqttClient.is_conn_issue() and connectionAttemptNumber <= maxConnectionAttempts:
        print(f"Failed to connect to MQTT server...trying again in {timeBetweenConnectionAttempts} seconds (reconnection attempt {connectionAttemptNumber})")
        mqttClient.reconnect()
        connectionAttemptNumber += 1
        sleep(timeBetweenConnectionAttempts)
    if not mqttClient.is_conn_issue():
        print(f"Connected to MQTT server at {secrets.mqttServerAddress}")
        if not mqttInitialConnectionMade:
            # Subscribe to any desired topics
            mqttClient.subscribe(b"homeassistant/status")
            # MQTT discovery for home assistant
            mqttClient.publish(f"homeassistant/sensor/{sensorName}/config", json.dumps(config), retain=True)
        else:
            mqttClient.resubscribe()
        return True
    else:
        print(f"Failed to connect to MQTT after {maxConnectionAttempts} tries")
        return False
connectToMQTT()
mqttInitialConnectionMade = True

###############################################################################################################
# Load cell setup
###############################################################################################################
loadCell = HX711(d_out=17, pd_sck=16)
loadCell.channel = HX711.CHANNEL_A_64
lastReportedWaterLevel = 0

while(True):
    # read load cell a number of times and get average value (try to ignore outliers)
    numberOfReads = 20
    rawValues = []
    for i in range(numberOfReads):
        rawValues.append(loadCell.read())
        sleep(1)
    rawValues.sort()
    start = (numberOfReads // 2) - (numberOfReads // 4)
    end = (numberOfReads // 2) + (numberOfReads // 4)
    rawValue = sum(rawValues[start: end]) / len(rawValues[start: end])
    # calculate water level from raw load cell values
    scaledValue = (rawValue - loadCellZeroValue) / loadCellScalingFactor
    waterLevel = math.floor((scaledValue - emptyBowlWeight))
    # if water level has changed, report water level to server
    percentDifference = (abs(lastReportedWaterLevel - waterLevel) / lastReportedWaterLevel) * 100 if lastReportedWaterLevel > 0 else 100
    print(f"Raw scale value: {rawValue}\t | \tScaled value: {scaledValue:.2f}\t | \tWater level: {waterLevel}\t | \tPercent change: {percentDifference}")
    if waterLevel >= 0 and percentDifference > reportingThreshold and connectToWiFi() and connectToMQTT():
        mqttClient.publish(stateTopic, json.dumps({'waterLevel': waterLevel}))
        print("Sensor value(s) sent to MQTT server")
        lastReportedWaterLevel = waterLevel
    # check for MQTT messages from subscribed topics
    mqttClient.check_msg()
    sleep(5)