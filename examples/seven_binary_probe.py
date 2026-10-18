"""Diagnostic phase-set probes, not accepted full-binary validation."""
import json
import shutil
import xml.etree.ElementTree as ET
from examples.seven_binary_variants import prepare
from examples.seven_binary_pandat import document
from examples.engine_runtime import pandat_executable
from examples.seven_binary_validation import FOLDER
from examples.pandat_batch import run_document
from src.storage import atomic_json

def run():
    base,db,_=prepare(('CO','FE'),'first')
    for name,phases,kind in [
        ('point_fcc',['FCC_A1'],'point'),
        ('point_all',list(db.phases),'point'),
        ('section_simple',['LIQUID','BCC_A2','FCC_A1','HCP_A3'],'section'),
        ('section_order',['LIQUID','BCC_A2','ORDER_B2','FCC_A1','FCC_L12','HCP_A3'],'section'),
    ]:
        folder=FOLDER/'import_diagnosis'/name
        folder.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(base/'model.tdb',folder/'model.tdb')
        root=ET.fromstring(document(('CO','FE'),phases,300,2011))
        calc=root.find('calculation'); calc.set('type',kind)
        if kind=='point':
            points=calc.find('system/points')
            for p in list(points)[1:]: points.remove(p)
            space=points.find('point/statespace'); space.find('T').set('value','1000')
            for n in space.findall('n'):n.set('value','0.5')
        tables=calc.find('output/tables')
        for t in list(tables):tables.remove(t)
        tab=ET.SubElement(tables,'table',name='point_0.dat',source='Default',type='Default')
        for col in ['T','x(*)','phase_name','G(@*)']:
            ET.SubElement(tab,'column',name=col)
        try:
            result=run_document(pandat_executable(),folder,ET.tostring(root,encoding='unicode'),1,timeout=15)
        except Exception as exc:result={'error':str(exc)}
        atomic_json(folder/'result.json',result)
        print(name,json.dumps(result),flush=True)

if __name__=='__main__':run()
