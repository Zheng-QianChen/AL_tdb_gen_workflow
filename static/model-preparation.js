'use strict';

// The legacy form remains available for standalone runs. A project model pins
// the run identity and derives every writable location from its server record.
let savedModelConfig=null;
async function prepareProjectModel(){
  if(!ToolShell.modelApi)return;
  const el=id=>document.getElementById(id);
  const save=el('save-json-btn');
  save.disabled=true;
  const main=el('main');
  main.inert=true;
  try{
    const m=await ToolShell.detail;
    el('sublattices-container').dataset.elements=m.elements.map(x=>x.toUpperCase()).join(', ');
    const fixed={'phase-name':m.phaseLabel,'custom-filename':m.config,'record-path':m.paths.record_path,
      'structure-out-file':m.paths.structure_out_file,'generate-dft-path':m.paths.generate_DFT_path,
      'calced-dft-path':m.paths.calced_DFT_path,'pkl-phase-path':m.paths.pkl_phase_path};
    for(const [id,value] of Object.entries(fixed)){el(id).value=value;el(id).readOnly=true;}
    if(m.configured){
      const res=await fetch('/get_config_status?filename='+encodeURIComponent(m.config));
      if(!res.ok)throw Error('读取模型配置失败');
      const data=await res.json();
      savedModelConfig=data;
      const t=data.tdb_model,al=data.AL_set;
      const fields={'structure-file':data.structure_file,'convert-to-primitive':data.structure_convert_to_primitive,
        'cif-sublatt':data.cif_sublatt||'','init-random-n':data.init_random_n,'sublattice-number':t.sublattice_number,
        'atom-ref-file':t.Atom_ref.file,'atom-ref-index':t.Atom_ref.index_name,'atom-ref-col':t.Atom_ref.col_name,
        'ml-model':al.ML_model,'ml-style':al.ML_style,'normalizer':al.normalizer,'eigen-weight':al.eigen_weight.join(', '),
        'pkl-show-control':al.pkl_show_control};
      for(const [id,value] of Object.entries(fields))el(id).value=value;
      generateSublattices(t.sublattice_number);
      document.querySelectorAll('.sublattice-item').forEach((item,i)=>{
        item.querySelector('.site2sub').value=JSON.stringify(t.site2sub?.[i]||[i]);
        item.querySelector('.occup-atoms').value=t.occup_atoms_in_tdb[i];
        item.querySelector('.allowed-elements').value=t.comp[i].join(', ');
      });
      el('descriptors-container').replaceChildren();
      for(const [file,table] of Object.entries(al.descriptor)){
        addDescriptorItem();
        const item=el('descriptors-container').lastElementChild;
        item.querySelector('.descriptor-file').value=file;item.querySelector('.descriptor-index').value=table.index_name;
        const columns=item.querySelector('.column-selector');columns.replaceChildren();
        for(const name of table.col_name){
          const label=document.createElement('label'),check=document.createElement('input');
          check.type='checkbox';check.className='column-checkbox';check.value=name;check.checked=true;
          label.append(check,document.createTextNode(' '+name+' '));columns.append(label);
        }
      }
      generateHyperParameters(al.ML_model);
      for(const input of document.querySelectorAll('.hyper-param')){
        if(Object.hasOwn(al.ML_hyper_parameters,input.dataset.name))
          input.value=al.ML_hyper_parameters[input.dataset.name]??'null';
      }
      el('ml-hyper-parameters-json').value=JSON.stringify(al.ML_hyper_parameters);
      for(const field of document.querySelectorAll('.quest-param'))field.value=al.quest[field.dataset.param];
    }else{
      el('structure-file').value='';el('atom-ref-file').value='';
      el('descriptors-container').replaceChildren();addDescriptorItem();
      document.querySelectorAll('.allowed-elements').forEach(input=>{input.value=m.elements.map(x=>x.toUpperCase()).join(', ');});
    }
    save.disabled=false;
  }catch(err){
    const message=document.createElement('p');message.setAttribute('role','alert');message.textContent=err.message;
    main.prepend(message);
  }finally{main.inert=false;}
}
document.addEventListener('DOMContentLoaded',prepareProjectModel);
