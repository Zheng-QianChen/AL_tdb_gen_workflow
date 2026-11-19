from pathlib import Path

from src.result_analysis import analyze_outcar, analyze_task_directory, parse_incar_text


def test_incar_allowlist_drops_unknown_keys():
    parsed = parse_incar_text("ENCUT = 400\nPASSWORD = secret\nNSW = 0\n")
    assert parsed["ENCUT"] == 400 and parsed["NSW"] == 0
    assert "PASSWORD" not in parsed


def test_outcar_analysis_null_timing_not_zero(tmp_path):
    (tmp_path / "INCAR").write_text("NSW = 0\nENCUT = 400\n")
    outcar = tmp_path / "OUTCAR"
    outcar.write_text(
        "vasp.6.3.0\n"
        "free  energy   TOTEN  = -8.0 eV\n"
        "General timing and accounting informations for this job:\n"
    )
    analysis = analyze_outcar(outcar, incar=parse_incar_text((tmp_path / "INCAR").read_text()))
    assert analysis["vasp_version"] == "6.3.0"
    assert analysis["energy_ev_cell"] == -8.0
    assert analysis["elapsed_seconds"] is None
    assert analysis["cpu_seconds"] is None
    assert analysis["elapsed_seconds"] != 0 and analysis["cpu_seconds"] != 0
    assert analysis["final_energy_definition"] == "free_energy_TOTEN"
    assert analysis["electronic_converged"] is None
    assert analysis['ionic_converged'] is None
    assert analysis['ionic_convergence_applicability'] == 'not_applicable'


def test_final_electronic_loop_overrides_earlier_success(tmp_path):
    outcar = tmp_path / 'OUTCAR'
    outcar.write_text('NELM = 60;\nIteration 1( 4)\n'
                      'aborting loop because EDIFF is reached\n'
                      'Iteration 2( 60)\nfree energy TOTEN = -4 eV\n'
                      'General timing and accounting\n')
    analysis = analyze_outcar(outcar, incar={'NSW': 10, 'IBRION': 2})
    assert analysis['electronic_converged'] is False
    assert analysis['electronic_steps_final'] == 60
    assert analysis['ionic_converged'] is False
    outcar.write_text(outcar.read_text().replace('Iteration 2( 60)', 'Iteration 2( 3)\naborting loop because EDIFF is reached'))
    assert analyze_outcar(outcar)['electronic_converged'] is True


def test_fractional_kpoints_are_preserved(tmp_path):
    (tmp_path / 'KPOINTS').write_text('explicit\n1\nReciprocal\n0.25 0.5 0.125 1\n')
    result = analyze_task_directory(tmp_path)
    assert result['analysis']['kpoints']['kpts'] == [[.25, .5, .125]]


def test_xml_uses_free_energy_and_totals_time(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.result_analysis import analyze_vasprun
    import pymatgen.io.vasp.outputs
    path = tmp_path / 'vasprun.xml'
    path.write_text('<modeling><time name="totals">40.0 12.5</time></modeling>')
    fake = SimpleNamespace(final_energy=-7, ionic_steps=[{'e_fr_energy': -8}],
                           incar={'NSW': 0}, parameters={'NSW': 0},
                           converged_electronic=None, converged_ionic=True)
    monkeypatch.setattr(pymatgen.io.vasp.outputs, 'Vasprun', lambda *a, **kw: fake)
    result = analyze_vasprun(path)
    assert result['energy_ev_cell'] == -8
    assert result['final_energy_definition'] == 'free_energy_TOTEN'
    assert result['elapsed_seconds'] == 12.5 and result['cpu_seconds'] == 40
    assert result['electronic_converged'] is None
    assert result['ionic_converged'] is None


def test_outcar_timing_when_present(tmp_path):
    text = (
        "vasp.5.4.4\n"
        "free  energy   TOTEN  = -1.5 eV\n"
        "General timing and accounting informations for this job:\n"
        "Elapsed time (sec):  12.5\n"
        "Total CPU time used (sec):  40.0\n"
    )
    (tmp_path / "OUTCAR").write_text(text)
    analysis = analyze_outcar(tmp_path / "OUTCAR")
    assert analysis["elapsed_seconds"] == 12.5
    assert analysis["cpu_seconds"] == 40.0


def test_task_directory_hashes_inputs(tmp_path):
    (tmp_path / "INCAR").write_text("ENCUT = 520\nKSPACING = 0.2\nNSW = 0\n")
    (tmp_path / "POSCAR").write_text("x\n")
    (tmp_path / "POTCAR").write_text("TITEL = PAW_PBE Al\n")
    (tmp_path / "OUTCAR").write_text(
        "vasp.6.4.1\nfree  energy   TOTEN  = -3 eV\n"
        "General timing and accounting informations for this job:\n")
    payload = analyze_task_directory(tmp_path, result_format="vasp/outcar", result_file="OUTCAR",
                                     metadata={"task_id": "task.000000", "endmember": "AL:AL"})
    assert payload["analysis"]["incar"]["ENCUT"] == 520
    assert payload["evidence"]["INCAR"] and payload["evidence"]["POSCAR"]
    assert payload["evidence"]["collect"]["endmember"] == "AL:AL"
