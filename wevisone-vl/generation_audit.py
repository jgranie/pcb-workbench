"""Report generation completion separately from detection correctness."""
import html,re

def analyze_generation(response,count,limit,eos_reached):
    limit_reached=count>=limit and not eos_reached
    unclosed=any(response.lower().count('<'+tag+'>')>response.lower().count('</'+tag+'>') for tag in ('box','point','polygon'))
    return {'generated_tokens':count,'max_new_tokens':limit,'eos_reached':bool(eos_reached),'limit_reached':limit_reached,'structure_incomplete':unclosed,'truncated':limit_reached,'response_complete':bool(eos_reached and not unclosed)}

def status_html(audit):
    if not audit:return ''
    if audit.get('truncated'):title='Résultat incomplet — limite de jetons atteinte';color='#ffbe75'
    elif audit.get('structure_incomplete'):title='Résultat à vérifier — format inachevé';color='#ffbe75'
    elif audit.get('response_complete'):title='Génération terminée — détections à valider';color='#90e1b2'
    else:title='Fin de génération non confirmée';color='#ffbe75'
    count=audit.get('generated_tokens','?');limit=audit.get('max_new_tokens','?')
    return f'<p role="status" style="padding:12px;border-left:3px solid {color};color:{color}"><b>{title}</b> · {count}/{limit} jetons</p>'
