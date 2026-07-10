from datetime import date, time

def is_slot_blocked(d: date, t: time) -> bool:
    """
    Comprova si una franja horària està bloquejada:
    - Dilluns, dimarts i divendres matins bloquejats (inici abans de les 12:00h).
    - Dimarts tarda bloquejat (inici a partir de les 15:00h).
    """
    # weekday(): 0=Dilluns, 1=Dimarts, 4=Divendres
    wd = d.weekday()
    
    # Dilluns, dimarts i divendres matins (< 12:00)
    if wd in (0, 1, 4) and t < time(12, 0):
        return True
        
    # Dimarts tarda (>= 15:00)
    if wd == 1 and t >= time(15, 0):
        return True
        
    return False
