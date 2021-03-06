import serial, time, io, datetime, math, os
from serial.tools.list_ports import comports

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as ani
import matplotlib.dates as mdates

from multiprocessing import Process, Pipe, Array

slack_url = ""


avg_time = 30.0# 1 minute moving average
pid_cycle_time = 0.001 # ms pid cycle

debug = False

hard_temp_limit = 240.0
hard_rate_limit = 5.0/60.0 # 5 deg/min

def set_ssr( port, chan, val ):
    if not debug:
        if chan == 0:
            port[0].dtr = val
        if chan == 1:
            port[0].rts = val
        if chan == 2:
            port[1].dtr = val
        if chan == 3:
            port[1].rts = val


def pid_loop(T_setp, prop_setp, assigned_tc, T_ramp_state, T_ramp, tc_data, tc_rate_min, tc_rate_hour, ssr_off, ssr_state, ssr_rb, pidctrl_state, ssr_avg_power):

    n_to_average = avg_time/pid_cycle_time

    power_sum = [[] for i in range(len(ssr_state))]

    ssr_port = []
    if not debug:
        ports = comports()

        for port in ports:
            print port
        port = ports[1]
        print "Opening ", ports[1], " for SSR control"
        print "Opening ", ports[2], " for SSR control"

        ssr_port.append(serial.Serial(ports[1], 9600, timeout= 1, parity=serial.PARITY_NONE, xonxoff=0, rtscts=False, dsrdtr=False, bytesize=8, stopbits=1))
        ssr_port.append(serial.Serial(ports[2], 9600, timeout= 1, parity=serial.PARITY_NONE, xonxoff=0, rtscts=False, dsrdtr=False, bytesize=8, stopbits=1))

        for p in ssr_port:
            p.close()
            p.open()

            p.dtr = False
            p.rts = False

    all_off = False
    while 1:

        if all_off:
            # Someone manually turned us back on
            for off_state in ssr_off:
                if not off_state:
                    all_off = False

        for tcval in tc_data:
            if tcval > hard_temp_limit and tcval < 10000.0 and not all_off:
                # Hit emergency limit
                print "TC val of ", tcval, " found"
                all_off = True
                # Push to slack
                if not debug:
                    os.system("curl -X POST -H \'Content-type: application/json\' --data \'{\"channel\": \"#c200\", \"text\":\"C200 shutting down!  Temperature saftey threshold met\"}\' %s"%  slack_url)
                else:
                    print "Would push emergency off notification to slack"


        for ssr in range(len(ssr_state)):
            if all_off:
                ssr_off[ssr] = True

            power_sum[ssr].append(ssr_state[ssr])
            if len(power_sum[ssr]) > n_to_average:
                power_sum[ssr].pop(0)
            
            ssr_avg_power[ssr] = sum(power_sum[ssr])/float(len(power_sum[ssr]))

            # Under control of PID
            if pidctrl_state[ssr]:
                calc_setpoint = 0.0

                diff = tc_data[assigned_tc[ssr]] -  T_setp[ssr];

                # Temp is low
                if diff < 0:
                    calc_setpoint = -prop_setp[ssr]*diff

                # Ramp rate is too high
                if T_ramp_state[ssr]:
                    ramp_x = 0.0
                    if abs(T_ramp[ssr]) > 1e-2:
                        ramp_x = 1.0 - (T_ramp[ssr] - tc_rate_min[assigned_tc[ssr]])/T_ramp[ssr]
                    else:
                        ramp_x = 0.0

                    if T_ramp[ssr] > 0.0:
                        if ramp_x > 1.0:
                            calc_setpoint = 0.0
                        else:
                            if ramp_x > 0.75:
                                calc_setpoint *= (ramp_x-0.75)/0.25

                    if T_ramp[ssr] < 0.0:
                        if ramp_x > 1.0:
                            calc_setpoint = 1.0
                        else:
                            if ramp_x > 0.75:
                                calc_setpoint *= (ramp_x-0.75)/0.25


                ramp_hard_x  = 1.0 - (hard_rate_limit- tc_rate_min[assigned_tc[ssr]])/hard_rate_limit
                if ramp_hard_x > 1.0:
                    calc_setpoint = 0.0
                else:
                    if ramp_hard_x > 0.75:
                        calc_setpoint *= (ramp_hard_x-0.75)/0.25

                if calc_setpoint < 0.0:
                    calc_setpoint = 0.0

                if calc_setpoint > 1.0:
                    calc_setpoint = 1.0

                ssr_rb[ssr] = calc_setpoint*100.0


            if ssr_state[ssr] and not ssr_off[ssr]:
                set_ssr(ssr_port, ssr, True)
            else:
                set_ssr(ssr_port, ssr, False)

        time.sleep(pid_cycle_time)

