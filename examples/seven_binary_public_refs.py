"""Public vendor reference tables: these are NOT raw experimental data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import itertools
import json
from pathlib import Path
from urllib.request import urlopen,Request
from lxml import html

ROOT=Path(__file__).resolve().parents[1]/'data/seven_element_validation_20261018'
PAIRS=list(itertools.combinations(('CO','CU','FE','NI','TA','TI','W'),2))

def fetch(pair):
    name='-'.join(pair);url='https://computherm.com/'+name.lower()
    item={'pair':name,'url':url,'kind':'vendor_calculated_reference_not_raw_experiment',
          'retrieved_utc':datetime.now(timezone.utc).isoformat()}
    try:
        response=urlopen(Request(url,headers={'User-Agent':'ThermodynamicResearch/1.0'}),timeout=35)
        data=response.read();page=html.fromstring(data)
        out=ROOT/'public_references';out.mkdir(exist_ok=True)
        (out/(name+'.html')).write_bytes(data)
        item['sha256']=hashlib.sha256(data).hexdigest()
        item['title']=page.xpath('string(//title)').strip()
        item['tables']=[]
        for table in page.xpath('//table'):
            rows=[[' '.join(''.join(c.itertext()).split()) for c in row.xpath('./td|./th')]
                  for row in table.xpath('.//tr')]
            if rows:item['tables'].append(rows)
        item['status']='retrieved'
    except Exception as exc:item.update(status='unavailable',error=str(exc))
    return item

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(fetch,PAIRS))
    (ROOT/'public_reference_tables.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    for item in results:print(item['pair'],item['status'],[len(t) for t in item.get('tables',[])])
