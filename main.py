from machine import Pin
from hx711 import HX711
import network
from umqtt.robust import MQTTClient
from time import sleep, time 
import json
import secrets

#INDICATE STARTUP
led = Pin('LED', Pin.OUT)

#information 
print("Booting...")

#turn the LED on first
led.value(1)  # type: ignore

#version
version=0.12

###############################################################################################################
# Config variables
###############################################################################################################
sensorName = "scale_sensor"                 # name of the sensor
sensorNameUp = sensorName + "_up"           # sensor of time aggregate change
sensorNameDown = sensorName + "_down"       # sensor of time aggregate change
sensorFriendlyName = "Scale Sensor"         # friendly name of sensor to be shown in Home Assistant (this is how the sensor will be shown in the HA frontend)
loadCellTareValue = -58818                  # load cell specific zero value (what does your load cell read with zero weight on it?) - raw value (not grams)
loadCellScalingFactor = -1/214              # scaling factor to convert raw value read from load cell to grams
weightCarrierWeight = 255                   # how many grams does the empty water bowl weigh?
sampleRate = 15                              # how many seconds per sample? 
absoluteDiffRoundDec = 100                  # decimals to round
gramConverstionRoundDec = 5                 # decimals to round again
absoluteDiffReportingThreshold = 10         # percent change for reporting
agg_timeout = 60 * 60 * 12                  # reset every N hours

###############################################################################################################
# WiFi setup
###############################################################################################################
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
def connectToWiFi():
    if wlan.isconnected():
        status = wlan.ifconfig()
        ##print(f"Connected to WiFi with IP: {status[0]}")
        return True
    ##print("Connecting to WiFi")
    wlan.connect(secrets.wifiSSID, secrets.wifiPassword)
    maxConnectionAttempts = 10
    timeBetweenConnectionAttempts = 60
    connectionAttemptNumber = 1
    while not wlan.isconnected() and connectionAttemptNumber <= maxConnectionAttempts:
        ##print(f"Failed to connect to WiFi...trying again in {timeBetweenConnectionAttempts} seconds (reconnection attempt {connectionAttemptNumber})")
        wlan.connect(secrets.wifiSSID, secrets.wifiPassword)
        connectionAttemptNumber += 1
        sleep(timeBetweenConnectionAttempts)
    if wlan.isconnected():
        status = wlan.ifconfig()
        ##print(f"Connected to WiFi with IP: {status[0]}")
        return True
    else:
        ##print(f"Failed to connect to WiFi after {maxConnectionAttempts} tries")
        return False
connectToWiFi()

###############################################################################################################
# MQTT setup
###############################################################################################################
stateTopic = f"homeassistant/{sensorName}/state"
stateTopicUp = f"homeassistant/{sensorNameUp}/state"
stateTopicDown = f"homeassistant/{sensorNameDown}/state"

config = {
    "name" : sensorFriendlyName,
    "state_topic": stateTopic,
    "value_template": "{{ value_json.weight }}",
    "unit_of_measurement": "g",
    "icon": "mdi:scale",
    "version" : version
}
config_up = {
    "name" : sensorFriendlyName + " Aggregate Increase",
    "state_topic": stateTopicUp,
    "value_template": "{{ value_json.weight }}",
    "unit_of_measurement": "g",
    "icon": "mdi:scale",
    "version" : version
}
config_down = {
    "name" : sensorFriendlyName + " Aggregate Decrease",
    "state_topic": stateTopicDown,
    "value_template": "{{ value_json.weight }}",
    "unit_of_measurement": "g",
    "icon": "mdi:scale",
    "version" : version
}
mqttClient = MQTTClient(sensorName, secrets.mqttServerAddress, user=secrets.mqttUsername, password=secrets.mqttPassword) if secrets.mqttUsername != "" and secrets.mqttPassword != "" else MQTTClient(sensorName, secrets.mqttServerAddress)
# MQTT callback
def onMQTTMessage(topic, msg, retain, dup):
    #print(f"MQTT message received on topic {topic} - message \"{msg}\"")
    if topic == b"homeassistant/status" and msg == b"online":
        #print("Home assistant restarted...resending sensor value(s)")
        if connectToWiFi() and connectToMQTT():
            mqttClient.publish(stateTopic, json.dumps({'weight': max(lastScaledDeltaToGrams - weightCarrierWeight, 0),}))
            mqttClient.publish(stateTopicUp, json.dumps({'weight':max(aggregate_up - weightCarrierWeight, 0),}))
            mqttClient.publish(stateTopicDown, json.dumps({'weight': max(aggregate_down - weightCarrierWeight, 0),}))

# connect MQTT
mqttClient.set_callback(onMQTTMessage)
mqttInitialConnectionMade = False
def connectToMQTT():
    if not mqttInitialConnectionMade:
        #print(f"Connecting to MQTT server at {secrets.mqttServerAddress}")
        mqttClient.connect()
    else:
        mqttClient.ping()
    maxConnectionAttempts = 10
    timeBetweenConnectionAttempts = 60
    connectionAttemptNumber = 1
    while mqttClient.is_conn_issue() and connectionAttemptNumber <= maxConnectionAttempts:
        #print(f"Failed to connect to MQTT server...trying again in {timeBetweenConnectionAttempts} seconds (reconnection attempt {connectionAttemptNumber})")
        mqttClient.reconnect()
        connectionAttemptNumber += 1
        sleep(timeBetweenConnectionAttempts)
    if not mqttClient.is_conn_issue():
        if not mqttInitialConnectionMade:
            #print(f"Connected to MQTT server at {secrets.mqttServerAddress}")
            # Subscribe to any desired topics
            mqttClient.subscribe(b"homeassistant/status")
            # MQTT discovery for home assistant
            mqttClient.publish(f"homeassistant/sensor/{sensorName}/config", json.dumps(config), retain=True)
            mqttClient.publish(f"homeassistant/sensor/{sensorNameUp}/config", json.dumps(config_up), retain=True)
            mqttClient.publish(f"homeassistant/sensor/{sensorNameDown}/config", json.dumps(config_down), retain=True)

        else:
            mqttClient.resubscribe()
        return True
    else:
        return False
    
connectToMQTT()
mqttInitialConnectionMade = True

###############################################################################################################
# Load cell setup
###############################################################################################################
loadCell = HX711(d_out=17, pd_sck=16)
loadCell.channel = HX711.CHANNEL_A_64
lastScaledDeltaToGrams = 0
transmitWeight = 0

#aggregation
aggregate_down = weightCarrierWeight
aggregate_up = weightCarrierWeight
start_time = time()

###############################################################################################################
# Sample averaging
###############################################################################################################
def performSample(size = 50, time = 2):
    #remove approximate loadcell read time of 0.02
    values = []
    for i in range(0, size):
        led.toggle()
        rawValue = loadCell.read()
        values.append(rawValue)
    values.sort()
    midVal = values[int(size/4) : int(size / 2)]
    return sum(midVal) /  len(midVal)

print("Starting...")
while(True):
    #toggle the LED to see if this is still working
    led.toggle()
    
    # read load cell and calculate water level in bowl
    rawValue = performSample()
    deltaFromTare = (rawValue - loadCellTareValue)
    roundedDeltaFromTare = int(deltaFromTare / absoluteDiffRoundDec) * absoluteDiffRoundDec
    
    #scale to zero
    scaledDeltaToGrams = max(int((roundedDeltaFromTare) * loadCellScalingFactor),0)
    scaledDeltaToGrams = int(scaledDeltaToGrams / gramConverstionRoundDec) * gramConverstionRoundDec
    scaledDeltaDifference = abs(lastScaledDeltaToGrams - scaledDeltaToGrams)
    
    #print(f"Tare: {loadCellTareValue}\t | Raw: {rawValue}\t | dRawRound: {roundedDeltaFromTare}\t | Scale: {scaledDeltaToGrams} | dScale (n-1): {lastScaledDeltaToGrams} | dScale: {scaledDeltaDifference} ")
    if (
            absoluteDiffReportingThreshold <= scaledDeltaDifference and 
            scaledDeltaToGrams != lastScaledDeltaToGrams and 
            connectToWiFi() and connectToMQTT()
        ):
        #change?
        if lastScaledDeltaToGrams > scaledDeltaToGrams:
            aggregate_down += max((lastScaledDeltaToGrams - scaledDeltaToGrams),0) #value of items removed from scale
            mqttClient.publish(stateTopicDown, json.dumps({
                'weight':  max(aggregate_down - weightCarrierWeight, 0),
            }))
        
        else:
            aggregate_up += max((scaledDeltaToGrams - lastScaledDeltaToGrams),0) #value of items added from scale
            mqttClient.publish(stateTopicUp, json.dumps({
                'weight':  max(aggregate_up - weightCarrierWeight, 0),
            }))
        
        #should reset? 
        if start_time - time() > agg_timeout:
            aggregate_down = weightCarrierWeight
            aggregate_up = weightCarrierWeight
            start_time = time()

        lastScaledDeltaToGrams = scaledDeltaToGrams 
        mqttClient.publish(stateTopic, json.dumps({
            'weight': max(scaledDeltaToGrams - weightCarrierWeight, 0),
        }))

    # check for MQTT messages from subscribed topics
    mqttClient.check_msg()
    sleep(sampleRate)