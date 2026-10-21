from pathlib import Path
import xml.etree.ElementTree as ET
from scripts.aam_repair.matsim_adapter import set_param
from scripts.aam_repair.make_small_cases import write_xml
root=Path('validation/aam-exploration-integration')
root.mkdir(exist_ok=True)
config=ET.parse('validation/choice-small-positive/drt.config.xml').getroot()
for name,value in dict(baseFare=0,maxAccessDistanceMiles=30,maxEgressDistanceMiles=30,
    minimumTripDistanceMiles=0,maximumRoutedCandidates=8,protectedAlternatives=3,
    candidateVertiports=10,initialExplorationFraction=1,allowCarAtHomeAlternatives='true',
    serviceStartTime=21600,serviceEndTime=79200).items():set_param(config,'aam',name,value)
set_param(config,'controler','lastIteration',1)
(root/'config.xml').write_text('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n'+ET.tostring(config,encoding='unicode'),encoding='utf-8')
