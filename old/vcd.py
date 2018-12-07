#!/usr/bin/env python

import os, sys
import re, yaml

from vcd import *
from optparse import OptionParser

defaults = {}
defaults["vcd"] = '0-0-waveform.vcd'
defaults["cfg"] = os.path.dirname(os.path.realpath(__file__)) + '/vcd_config/config.yaml'

usage = "usage: %prog [options] <vcd-file>"
optparser = OptionParser(usage)
optparser.add_option("--config", dest="config", default=defaults["cfg"],
                    help="config yaml containing the signals to be parsed for output")

(options, args) = optparser.parse_args()

class BaseWatcher(object):
	'''Reimplement base class for watcher objects to only contain instance vars'''
	'''This prevents multiple watcher objects from sharing the same data (though less efficient)'''

	def __init__(self):
		self.sensitive = []
		self.watching = []
		self.trackers = []
		self.default_hierarchy = None

		self._sensitive_ids = []
		self._watching_ids = []

		self.tracker = None
		self.parser = None

		self.values = None
		self.activity = None

	def notify(self, activity, values):
		'''Manage internal data updates prior to calling the expected to be overridden update method'''
		self.values = values
		self.activity = activity
		self.update()

	def update(self):
		'''Override update to only check on rising/ falling edges etc, prior to calling manage trackers'''
		self.manage_trackers()


	def manage_trackers(self):
		'''Start new trackers, update existing trackers and clean up finished tracker objects'''
		if self.start_tracker():
			self.trackers.append(self.create_new_tracker())

		for tracker in self.trackers:
			tracker.notify(self.activity, self.values)

		for tracker in self.trackers:
			if tracker.finished:
				self.trackers.remove(tracker)


	def start_tracker(self):
		'''Override start_tracker to identify start of transaction conditions'''
		return False


	def create_new_tracker(self):
		'''Build an instance of the pre-defined transaction tracker objects'''
		return self.tracker(self.parser, self)


	def update_ids(self):
		'''Callback after VCD header is parsed, to extract signal ids'''
		self._sensitive_ids = {xmr : self.parser.get_id(xmr) for xmr in self.sensitive}
		self._watching_ids = {xmr : self.parser.get_id(xmr) for xmr in self.watching}


	def set_hierarchy(self, hierarchy):
		'''Set the prefix path for signals'''
		self.default_hierarchy = hierarchy


	def add_sensitive(self, signal, hierarchy=None):
		'''Add a signal to the sensitivity and watch lists'''
		if not hierarchy:
			hierarchy = self.default_hierarchy
		self.sensitive.append(hierarchy + '.' + signal)
		self.watching.append(hierarchy + '.' + signal)


	def add_watching(self, signal, hierarchy=None):
		'''Register a signal to be watched'''
		if not hierarchy:
			hierarchy = self.default_hierarchy
		self.watching.append(hierarchy + '.' + signal)


	def add_parser(self, parser):
		self.parser = parser


	def get_sensitive_ids(self):
		'''Parser access function for sensitivity list ids'''
		return self._sensitive_ids.values()


	def get_watching_ids(self):
		'''Parser access function for watch list ids'''
		return self._watching_ids.values()


	def get_id(self, signal, hierarchy=None):
		'''Look up the signal id from a signal name and optional path'''
		if not hierarchy:
			hierarchy = self.default_hierarchy

		if not hierarchy:
			return None

		xmr = hierarchy + '.' + signal
		if xmr in self._watching_ids:
			return self._watching_ids[xmr]
		else:
			return None


	def __getattribute__(self, name):

		if name in ['get_id', 'default_hierarchy', '_watching_ids']:
			return object.__getattribute__(self, name)

		id = self.get_id(name)
		if id:
			return self.values[id]
		else:
			return object.__getattribute__(self, name)


	def get2val(self, signal):
		'''Attempt to convert a scalar to a numerical 0/1 value'''
		id = self.get_id(signal)
		if id in self.values:
			value = self.values[id]
			if value in "xXzZ":
				raise ValueError
			return eval(value)


	def get_active_2val(self, signal):
		'''Attempt to convert a scalar to a numerical 0/1 value'''
		id = self.get_id(signal)
		if id in self.activity:
			value = self.activity[id]
			if value in "xXzZ":
				raise ValueError
			return eval(value)


	def set_tracker(self, tracker):
		'''Set the class type of a tracker object, used for the tracker creation'''
		self.tracker = tracker


class NodeWatcher(BaseWatcher):

	in_reset = False

	def __init__(self, hierarchy = None):
		super(NodeWatcher, self).__init__()
		# set the hierarchical path first, prior to adding signals
		# so they all get the correct prefix paths
		self.set_hierarchy(hierarchy)

	def add_signals(self, signals):
		# Signals in the 'sensitivity list' are automatically added to the watch list
		self.add_sensitive('i_clk')
		self.add_sensitive('i_reset_n')

		for signal in signals:
			self.add_watching(signal)

	def update(self):
		# Called every time something in the 'sensitivity list' changes 
		# Doing effective posedge/ negedge checks here and reset/ clock behaviour filtering
		if self.get_id('i_reset_n') in self.activity and not self.get_active_2val('i_reset_n'):
			self.in_reset = True
			return

		if  self.get_id('i_reset_n') in self.activity and self.get_active_2val('i_reset_n') and self.in_reset:
			self.in_reset = False

		# Only update on rising clock edge (clock has changed and is 1)
		if  self.get_id('i_clk') in self.activity and self.get_active_2val('i_clk') and not self.in_reset:
			self.manage_trackers()

	def register_tracker(self, tracker):
		self.trackers.append(tracker)


class NodeTracker(tracker.VcdTracker):

	def configure(self, name, control, payload):
		self.intf = name
		self.control = []
		self.payload = []
		self.add_control(control)
		self.add_payload(payload)

	def add_control(self, signals):
		self.control.extend(signals)
	
	def add_payload(self, signals):
		self.payload.extend(signals)

	def update(self):
		# only support ANDing protocol signals together for now
		count = 0 

		for ctl in self.control:
			#val = v2d(getattr(self, ctl))
			#if (val > 0):
			if eval(getattr(self, ctl)) == 1:
				count = count + 1
			else:
				return

			if (count == len(self.control)):
				dump = "@%s %s: " % (self.parser.now, self.intf)
				for pd in self.payload:
					val = v2d(getattr(self, pd))
					dump = dump + "%s=0x%x " % (pd, val)
				print dump
				return

def main():
	vcd  = parser.VcdParser()
	data = yaml.safe_load(open(options.config))	
	for node in data:
		control = []
		payload = []

		for sig in node['protocol']:
			control.append(sig)

		for sig in node['payload']:
			payload.append(sig)

		print node['name']
		print '    Control signals: ', control
		print '    Payload signals: ', payload

		watcher = NodeWatcher(node['hier'])
		watcher.add_signals(control+payload)

		tracker = NodeTracker(vcd, watcher)
		tracker.configure(node['name'], control, payload)

		watcher.register_tracker(tracker)
		vcd.register_watcher(watcher)

	if (len(args) > 0) :
		vcdfile = args[0]
	else :
		vcdfile = defaults["vcd"]

	with open(vcdfile) as vcd_file:
		vcd.parse(vcd_file)
		#vcd.show_nets()


if __name__ == '__main__':
    main()
