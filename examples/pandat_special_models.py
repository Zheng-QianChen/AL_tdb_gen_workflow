"""Synthetic controls for vacancy/interstitial and magnetic coupling tests."""
from examples.pandat_models import cef_tdb


def magnetic_ordering_tdb(n=2, interstitial=False, afm=False, dialect="DISORDERED_PART", variable_interstitial=False):
    text = cef_tdb(n, "partitioned", ratios=[1/n]*n, ordering_keyword=dialect)
    text = text.replace("PHASE DIS %", "TYPE_DEFINITION M GES AMEND_PHASE_DESCRIPTION DIS MAGNETIC -1 0.4 !\n"
                        "TYPE_DEFINITION N GES AMEND_PHASE_DESCRIPTION TEST MAGNETIC -1 0.4 !\nPHASE DIS %M")
    text = text.replace("PHASE TEST %&", "PHASE TEST %&N")
    sign = -1 if afm else 1
    for element in ("AL", "NI"):
        text += f"PARAMETER TC(DIS,{element};0) 298.15 {sign*1000}; 6000 N !\n"
        text += f"PARAMETER BMAGN(DIS,{element};0) 298.15 {sign*2}; 6000 N !\n"
    # A temperature-independent ordering correction to the magnetic parameters.
    # Explicit endmembers produce positive changes for unlike occupations.
    import itertools
    for member in itertools.product(("AL", "NI"), repeat=n):
        if len(set(member)) > 1:
            text += f"PARAMETER TC(TEST,{':'.join(member)};0) 298.15 {sign*600}; 6000 N !\n"
            text += f"PARAMETER BMAGN(TEST,{':'.join(member)};0) 298.15 {sign*.8}; 6000 N !\n"
    if interstitial or variable_interstitial:
        # A fixed vacancy sublattice is a normalization/mapping control; the
        # variable C/VA tests use a separate synthetic model and real Fe-C.
        text = text.replace("TYPE_DEFINITION %", "ELEMENT VA VACUUM 0 0 0 !\nTYPE_DEFINITION %")
        text = text.replace("PHASE DIS %M 1 1 !", "PHASE DIS %M 2 1 3 !")
        text = text.replace("CONSTITUENT DIS :AL,NI:", "CONSTITUENT DIS :AL,NI:VA:")
        prefix = f"PHASE TEST %&N {n} " + " ".join(map(str, [1/n]*n))
        text = text.replace(prefix + " !", prefix.replace(f"%&N {n}", f"%&N {n+1}") + " 3 !")
        text = text.replace("CONSTITUENT TEST :" + "AL,NI:"*n, "CONSTITUENT TEST :" + "AL,NI:"*n + "VA:")
        import re
        text = re.sub(r"(PARAMETER \w+\((?:DIS|TEST),[^;]+)(;)", r"\1:VA\2", text)
    if variable_interstitial:
        text = text.replace("ELEMENT VA", "ELEMENT C GRAPHITE 12.011 0 0 !\nELEMENT VA")
        text = text.replace(":VA: !", ":C,VA: !")
        carbon_parameters = []
        for line in text.splitlines():
            if line.startswith("PARAMETER ") and ":VA;0)" in line:
                carbon = line.replace(":VA;0)", ":C;0)")
                if line.startswith("PARAMETER G("):
                    carbon = carbon.replace("; 6000", "+3000-6*T; 6000")
                carbon_parameters.append(carbon)
        text += "\n".join(carbon_parameters)+"\n"
    return text


INTERSTITIAL = """$ SYNTHETIC ONLY
ELEMENT FE BCC_A2 55.845 0 0 !
ELEMENT C GRAPHITE 12.011 0 0 !
ELEMENT VA VACUUM 0 0 0 !
TYPE_DEFINITION % SEQ * !
PHASE TEST % 2 1 3 !
CONSTITUENT TEST :FE:C,VA: !
PARAMETER G(TEST,FE:VA;0) 298.15 -10000; 6000 N !
PARAMETER G(TEST,FE:C;0) 298.15 20000-10*T; 6000 N !
"""
