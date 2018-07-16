#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.
"""
An example using the vcd parsing library. This parses VCD output from the UBUS
example shipped with the UVM BCL.

This example can be extended to provide interleaved transaction recording, using
UbusTrackers that exist for a transaction lifetime, or just extend the simple tracker 
below to filter/analyze a subset of signals within the VCD dump.
"""

import logging
import vcd
import sys


class UbusRisingClockWatcher(vcd.VCDWatcher):
    def __init__(self, parser, **kwds):
        # Assume we start in reset, to simplify tracker notification
        self.in_reset = True
        super().__init__(parser, **kwds)

    def should_notify(self):
        # Called every time something in the sensitivity list changes
        # This watcher looks for reset to trigger, then notifies trackers only on
        # rising clock edges.
        if self.get_id("ubus_tb_top.vif.sig_reset") in self.activity:
            try:
                # exception if this is X or Z
                if self.get_active_2val("ubus_tb_top.vif.sig_reset"):
                    print("in RESET")
                    self.in_reset = True
                    return False
                elif self.in_reset:
                    print("out of RESET")
                    self.in_reset = False
            except ValueError:
                return False

        if (
            self.get_id("ubus_tb_top.vif.sig_clock") in self.activity
            and self.get_active_2val("ubus_tb_top.vif.sig_clock")
            and not self.in_reset
        ):
            return True
        return False


class UbusTracker(vcd.VCDTracker):
    skip = False
    states = {}
    state = None

    def start(self):
        self.states = {
            "IDLE": self.idle_state,
            "START": self.start_state,
            "READ": self.data_state,
            "WRITE": self.data_state,
        }
        self.state = self.states["IDLE"]

    def update(self):
        self.state()

    def idle_state(self):
        if self["ubus_tb_top.vif.sig_start"]:
            if not self.skip:
                print("START @{}".format(self.parser.now))
            self.state = self.states["START"]

    def start_state(self):
        if self["ubus_tb_top.vif.sig_write"] == "1":
            print(
                "WRITE addr: {:#x}".format(
                    vcd.v2d(self["ubus_tb_top.vif.sig_addr"])
                )
            )
            self.state = self.states["WRITE"]
            return

        if self["ubus_tb_top.vif.sig_read"] == "1":
            print(
                "READ addr: {:#x}".format(
                    vcd.v2d(self["ubus_tb_top.vif.sig_addr"])
                )
            )
            self.state = self.states["READ"]
            return

        self.skip = True
        self.state = self.states["IDLE"]

    def data_state(self):
        if self["ubus_tb_top.vif.sig_wait"] == "1":
            return
        print(
            "     DATA: {:#x}".format(
                vcd.v2d(self["ubus_tb_top.vif.sig_data"])
            )
        )
        self.skip = False
        self.state = self.states["IDLE"]
        # Uncommenting the below kills the tracker after 1 transaction
        #self.finished = True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ubus_test.py <input-file.vcd>")
        exit(1)

    # test, so let's see everything
    logging.basicConfig()
    logger = logging.getLogger()
    #logger.setLevel(logging.DEBUG)

    # Create a parser object
    #parser = vcd.VCDParser(log_level=logging.DEBUG)
    parser = vcd.VCDParser(log_level=logging.INFO)

    # And a tracker
    tracker = UbusTracker()

    # attach a watcher within the hierarchy and start running
    watcher = UbusRisingClockWatcher(
        parser,
        sensitive=["ubus_tb_top.vif.sig_clock", "ubus_tb_top.vif.sig_reset"],
        watch=[
            "ubus_tb_top.vif.sig_request",
            "ubus_tb_top.vif.sig_grant",
            "ubus_tb_top.vif.sig_addr",
            "ubus_tb_top.vif.sig_size",
            "ubus_tb_top.vif.sig_read",
            "ubus_tb_top.vif.sig_write",
            "ubus_tb_top.vif.sig_start",
            "ubus_tb_top.vif.sig_bip",
            "ubus_tb_top.vif.sig_data",
            "ubus_tb_top.vif.sig_data_out",
            "ubus_tb_top.vif.sig_wait",
            "ubus_tb_top.vif.sig_error",
        ],
        trackers=[tracker],
    )

    with open(sys.argv[1]) as vcd_file:
        parser.parse(vcd_file)
