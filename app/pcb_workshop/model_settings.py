"""Validated per-action options within the existing inference budgets."""
import math


def defaults(kind):
    if kind not in ('board','epoxy','solders'):
        raise ValueError("Action WeVisOne inconnue.")
    value={'model_size':'2B','query':'printed circuit board' if kind=='board' else 'green insulating board surface',
           'vision_max_pixels':524288,'max_new_tokens':512,'temperature':0.,'top_p':.95,
           'top_k':50,'repetition_penalty':1.05,'mask_threshold':128}
    if kind=='solders':
        value.update(query='individual silver-gray solder joints at component terminals',max_new_tokens=2048);value.pop('mask_threshold')
    if kind=='epoxy':value.update(lab_a_threshold=None,bilateral_diameter=7,bilateral_sigma_color=15.,bilateral_sigma_space=5.)
    return value


def validate(kind, value=None):
    result=defaults(kind)
    if value is None:return result
    if not isinstance(value,dict) or set(value)-set(result):
        raise ValueError("Paramètres WeVisOne inconnus.")
    result.update(value)
    if result["model_size"] not in ("2B","4B"):
        raise ValueError("Taille du modèle : 2B ou 4B.")
    query=result['query']
    query_limit=1000 if kind=='solders' else 200
    if not isinstance(query,str) or not 1<=len(query.strip())<=query_limit or '\n' in query or '\r' in query:
        raise ValueError(f"Description : une ligne de 1 à {query_limit} caractères.")
    result['query']=query.strip()
    ranges={'vision_max_pixels':(16384,524288,True),'max_new_tokens':(1,2048 if kind=='solders' else 512,True),
            'temperature':(0,2,False),'top_p':(.01,1,False),'top_k':(0,100,True),
            'repetition_penalty':(.5,2,False),'mask_threshold':(1,254,True)}
    if kind=='solders':ranges.pop('mask_threshold')
    if kind=='epoxy':ranges.update(lab_a_threshold=(0,255,False),bilateral_diameter=(3,15,True),bilateral_sigma_color=(1,50,False),bilateral_sigma_space=(1,20,False))
    for key,(low,high,integer) in ranges.items():
        item=result[key]
        if key=='lab_a_threshold' and item is None:continue
        if isinstance(item,bool) or not isinstance(item,(int,float)) or not math.isfinite(item) or not low<=item<=high or integer and type(item) is not int:
            raise ValueError(f"{key} : valeur attendue entre {low} et {high}." )
    if kind=='epoxy' and result['bilateral_diameter']%2!=1:
        raise ValueError("Diamètre bilatéral : entier impair.")
    return result
