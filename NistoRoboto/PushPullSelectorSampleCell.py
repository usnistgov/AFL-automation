
class PushPullSelectorSampleCell(SampleCell):
	'''
		Class for a sample cell consisting of a pump and a one-to-many flow selector 
		where the pump line holds sample (pulling and pushing as necessary) with a cell on 
		a separate selector channel (in contrast to an inline selector cell where the cell is in the pump line).

		@TODO: write support for multiple cells on separate channels (up to 6 cells on a 10-position selector)
		@TODO: figure out when/where to pull in air to the syringe to make up for extra_vol_to_empty_ml


	'''

	sample_to_hold_volume_ml = 4
	sample_to_cell_volume_ml = 6
	extra_vol_to_empty_ml = 1
	rinse_vol_ml = 6
	nrinses_syringe = 2
	nrinses_cell = 2

	def __init__(self,name=None,thickness=None,state='clean',pump,selector):
		'''
			Name = the cell name, recognizable by the daq software

			thickness = cell path length, to be incorporated into metadata

			cell state if not 'clean'

			pump: a pump object supporting withdraw() and dispense() methods
				e.g. pump = NE1KSyringePump(port,syringe_id_mm,syringe_volume)

			selector: a selector object supporting string-based selectport() method with options 'sample','cell','rinse','waste','air'
				e.g. selector = ViciMultiposSelector(port,portlabels={'sample':1,'cell':2,'rinse':3,'waste':4,'air':5})

		'''
		self.name = name
		self.pump = pump
		self.selector = selector
		self.state = 'clean'


	def loadSample(self):

		if self.state is 'dirty':
			self.rinseAll()

		if self.state is 'clean':
			self.selector.selectport('sample')
			self.pump.withdraw(sample_to_hold_volume_ml)
			self.selector.selectport('cell')
			self.pump.dispense(sample_to_cell_volume_ml)
			self.state = 'loaded'


	def sampleToWaste(self):
			self.selector.selectport('sample')
			self.pump.withdraw(sample_to_cell_volume_ml + extra_vol_to_empty_ml)
			self.selector.selectport('waste')
			self.pump.dispense(sample_to_waste_volume_ml)

	def rinseSyringe(self):
		for i in range(nrinses_syringe):
			self.selector.selectport('rinse')
			self.pump.withdraw(rinse_vol_ml)
			self.selector.selectport('waste')
			self.pump.dispense(rinse_vol_ml)

	def rinseCell(self):
		#rinse the cell
		for i in range(nrinses_cell):	
			self.selector.selectport('rinse')
			self.pump.withdraw(rinse_vol_ml)
			self.selector.selectport('cell')
			for i in range(3): #swish the fluid around in the cell
				self.pump.dispense(rinse_vol_ml)
				self.pump.withdraw(rinse_vol_ml)
			self.selector.selectport('waste')
			self.pump.dispense(rinse_vol_ml + extra_vol_to_empty_ml)

	def rinseSampleLoadPort(self):
		for i in range(nrinses_sampleport):
			self.selector.selectport('rinse')
			self.pump.withdraw(rinse_vol_ml)
			self.selector.selectport('sample')
			for i in range(3): #swish the fluid around in the cell
				self.pump.dispense(rinse_vol_ml+sample_to_hold_volume_ml)
				self.pump.withdraw(rinse_vol_ml+sample_to_hold_volume_ml)
			self.selector.selectport('waste')
			self.pump.dispense(rinse_vol_ml + extra_vol_to_empty_ml)

	def rinseAll(self):
		if self.state is 'loaded':
			self.sampleToWaste()
		self.rinseSyringe()
		self.rinseCell()


