"""清洗引擎：单位登记与仿射换算、单元格数值解析、抽取行规整、
逐行清洗以及重复/冲突识别。仅依赖标准库。

由 run_clean.py 导入使用；本文件不提供命令行入口。
"""

import csv ,json ,re 

from pathlib import Path 

ENGINE_VERSION ="1.0.0"

MISSING_TOKENS ={"","-","--","\u2014","\u2013","na","n/a","nan","none","null","nr","n.r","n.r.",
"n.d.","nd","not reported","\u672a\u62a5\u544a","tbd"}

SUPERSCRIPTS =str .maketrans ("\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207b\u207a",
"0123456789-+")

NUMBER_PATTERN =r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"

UNIT_SUFFIX =r"(?:\s*([A-Za-z%\u00b0\u00b5\u03bc][A-Za-z0-9%\u00b0\u00b5\u03bc*/.^\-]*))?"

SUBSCRIPTS =str .maketrans ("\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089","0123456789")


def read_text_file (prs ):
    blob =Path (prs ).read_bytes ()
    for enc in ("utf-8-sig","utf-8","gb18030","latin-1"):
        try :
            tbl =blob .decode (enc )
            return tbl ,enc ,tbl .count ("\ufffd"),None 
        except UnicodeDecodeError :
            continue 
    return blob .decode ("latin-1","replace"),"latin-1",1 ,"decode_fallback"


def read_json (prs ):
    tbl ,ent ,new ,err =read_text_file (prs )
    if err :
        return None ,err 
    try :
        return json .loads (tbl ),None 
    except Exception as exc :
        return None ,"json_error:%s"%exc 


def write_json (prs ,shiftv ):
    Path (prs ).write_text (json .dumps (shiftv ,ensure_ascii =False ,indent =2 )+"\n",encoding ="utf-8")


def write_csv (prs ,records ,fields ):
    with open (prs ,"w",newline ="",encoding ="utf-8")as fh :
        w =csv .DictWriter (fh ,fieldnames =fields ,extrasaction ="ignore")
        w .writeheader ()
        w .writerows ({nmk :(""if rec .get (nmk )is None else rec .get (nmk ))for nmk in fields }for rec in records )


def natural_parts (rg ):
    return [int (tbl )if tbl .isdigit ()else tbl for tbl in re .split (r"(\d+)",str (rg ))]


def show_num (x ,sig =6 ):
    if x is None or x =="":
        return ""
    if isinstance (x ,str ):
        return x 
    if x ==0 :
        return "0"
    if abs (x )>=1e6 or abs (x )<1e-4 :
        return ("%.*e"%(sig -1 ,x )).replace ("e+","e").replace ("e-0","e-")
    return "%.*g"%(sig ,x )


class UnitRegistry :

    def __init__ (rg ,tbl ):
    # 资源用「对列表」存映射，这里转成 dict 方便查表
        rg .pf =dict (tbl .get ("prefixes",[]))
        rg .base =dict (tbl .get ("dimensions",[]))
        rg .canon =dict (tbl .get ("signature_targets",[]))
        rg .unk ={str (x ).lower ()for x in tbl .get ("reject_tokens",[])}
        rg .sym ={}
        for item in tbl .get ("units",[]):
            ent =(dict (item .get ("dirs",{})),float (item .get ("to_base",1.0 )),
            float (item .get ("shift",0.0 )))
            rg .sym [item ["sym"]]=ent 
            for old in item .get ("spellings",[]):
                rg .sym .setdefault (old ,ent )

    def atom_of (rg ,tbl ):
        if tbl in ("1","1.0"):
            return {},1.0 ,0.0 
        mtc =re .fullmatch (r"([A-Za-z%\u00b0\u00b5\u03bc\u2030]+)(?:\^?([+-]?\d+))?",tbl )
        if not mtc :
            return None 
        sym ,powv ,hit =mtc .group (1 ),int (mtc .group (2 )or 1 ),None 
        if sym in rg .sym :
            hit =rg .sym [sym ]
        else :
            for pos in range (len (sym )-1 ,0 ,-1 ):
                prs ,rest =sym [:pos ],sym [pos :]
                if prs in rg .pf and rest in rg .sym :
                    dmap ,scl ,shiftv =rg .sym [rest ]
                    hit =(dmap ,scl *rg .pf [prs ],0.0 )
                    break 
        if hit is None :
            return None 
        dmap ,scl ,shiftv =hit 
        return {nmk :val *powv for nmk ,val in dmap .items ()},scl **powv ,shiftv if powv ==1 else 0.0 

    def parse_unit (rg ,body ):
        if body is None :
            return None 
        blob =str (body ).strip ()
        if not blob or blob .lower ()in rg .unk :
            return None 
        for old ,new in (("\u2212","-"),("\u00b7","*"),("\u22c5","*"),("\u00d7","*"),
        ("\u00b5","u"),("\u03bc","u"),("\u00a0"," ")):
            blob =blob .replace (old ,new )
        dims ,scl ,sgn ,offs ,cnt ={},1.0 ,1 ,0.0 ,0 
        for part in re .findall (r"[*/]|[^\s*/]+",re .sub (r"\(.*?\)|\[.*?\]"," ",blob )):
            if part in ("*","/"):
                sgn =1 if part =="*"else -1 
                continue 
            hit =rg .atom_of (part )
            if hit is None :
                return None 
            dmap ,f ,shiftv =hit 
            for nmk ,val in dmap .items ():
                dims [nmk ]=dims .get (nmk ,0 )+val *sgn 
            scl *=f **sgn 
            offs +=shiftv if sgn ==1 else 0.0 
            cnt +=1 
        return {"dim":{nmk :val for nmk ,val in dims .items ()if val },"scale":scl ,
        "offset":offs if cnt ==1 else 0.0 }

    def to_canonical (rg ,orig ):
        """返回 {unit, derived, factor, offset}，且保证 after = before*factor + offset。"""
        prs =rg .parse_unit (orig )
        if prs is None :
            return None 
        sig ="|".join ("%s^%d"%(nmk ,prs ["dim"][nmk ])for nmk in sorted (prs ["dim"])if prs ["dim"][nmk ])
        label ,derived =rg .canon .get (sig ),False 
        if label is None :# 量纲组合不在登记表：改用基准单位拼派生规范单位
            label ="*".join ("%s^%d"%(rg .base .get (nmk ,nmk ),prs ["dim"][nmk ])for nmk in sorted (prs ["dim"]))or "1"
            derived =True 
        tbl =rg .parse_unit (label )or {"scale":1.0 ,"offset":0.0 }
        return {"unit":label ,"derived":derived ,"factor":prs ["scale"]/tbl ["scale"],
        "offset":(prs ["offset"]-tbl ["offset"])/tbl ["scale"]}


def parse_cell (blob ):
    """解析单元格：单值 / 区间 / 值±误差 / 缺失 / 文本；若单元格内嵌单位也一并抽出。"""
    cell ={"kind":"missing","raw":""if blob is None else str (blob )}
    if blob is None :
        return cell 
    tbl =str (blob ).strip ().translate (SUPERSCRIPTS )
    for old ,new in (("\u2212","-"),("\u2013","-"),("\u2014","-"),("\u00d7","x"),
    ("\u00a0"," "),("\u2264","<="),("\u2265",">="),("\u2248","~")):
        tbl =tbl .replace (old ,new )
    tbl =re .sub (r"\s*[xX*]\s*10\s*\^?\s*([+-]?\d+)",r"e\1",tbl )
    tbl =re .sub (r"\(([^)]*)\)"," ",tbl )
    stmt =tbl .strip ().strip (";,").strip ()
    if stmt .lower ().rstrip (".")in MISSING_TOKENS :
        return cell 
    ineq =""
    mtc =re .match (r"^(<=|>=|<|>|~|ca\.?|about|approx\.?)\s*",stmt ,flags =re .I )
    if mtc :
        ineq ,stmt =mtc .group (1 ),stmt [mtc .end ():].strip ()
    stmt =stmt .replace ("+/-","\u00b1").replace ("+-","\u00b1")
    if "\u00b1"in stmt :
        old ,new =stmt .split ("\u00b1",1 )
        mnum ,enumv =re .search (NUMBER_PATTERN ,old .replace (" ","")),re .search (NUMBER_PATTERN ,new .replace (" ",""))
        if mnum and enumv :
            return {"kind":"error","raw":cell ["raw"],"ineq":ineq ,
            "value":float (mnum .group (0 ).replace (",","")),"err":abs (float (enumv .group (0 ).replace (",","")))}
    if re .fullmatch (r"[0-9eE.,+\-\s]*",stmt ):
        stmt =stmt .replace (" ","")
    mtc =re .fullmatch (r"(%s)(?:-|~|to)(%s)%s"%(NUMBER_PATTERN ,NUMBER_PATTERN ,UNIT_SUFFIX ),stmt ,flags =re .I )
    if mtc :
        old ,new =float (mtc .group (1 ).replace (",","")),float (mtc .group (2 ).replace (",",""))
        cell .update (kind="range",low =min (old ,new ),high =max (old ,new ),ineq =ineq ,swapped =old >new ,unit =(mtc .group (3 )or "").strip ())
        return cell 
    mtc =re .fullmatch (r"(%s)%s"%(NUMBER_PATTERN ,UNIT_SUFFIX ),stmt ,flags =re .I )
    if mtc :
        cell .update (kind="number",ineq =ineq ,unit =(mtc .group (2 )or "").strip (),
        value =float (mtc .group (1 ).replace (",","")))
        return cell 
    return {"kind":"text","raw":cell ["raw"]}


def key_form (rg ):
    tbl =str (rg or "").strip ().translate (SUBSCRIPTS ).lower ().replace ("\u2013","-").replace ("\u2014","-")
    return re .sub (r"\s+"," ",tbl ).strip (" .;,:*")


def split_unit_header (label ):
    """拆分列名内嵌单位：'带隙 (eV)' → ('带隙', 'eV')。"""
    rg =str (label ).strip ()
    mtc =re .search (r"[（(]\s*([^)）]{1,18})\s*[)）]\s*$",rg )
    if mtc :
        return rg [:mtc .start ()].strip (),mtc .group (1 ).strip ()
    if "/"in rg :
        hit ,tbl =rg .rsplit ("/",1 )
        if hit .strip ()and re .fullmatch (r"[A-Za-z%\u00b0\u00b5\u03bc][A-Za-z0-9%\u00b0\u00b5\u03bc*^.\-]*",tbl .strip ()):
            return hit .strip (),tbl .strip ()
    return rg ,""


def classify_columns (cols ,fsyn ):
    roles ,used ={},set ()
    for role in ("row_id","source_document_id","source_locator","unit","value","indicator","material"):
        keys =[str (nmk ).lower ().replace ("-","_").replace (" ","_")for nmk in fsyn .get (role ,[])]
        pick =None 
        for col in cols :
            if col in used :
                continue 
            low =str (col ).lower ().replace ("-","_").replace (" ","_")
            if low in keys :
                pick =(0 ,keys .index (low ),col )
                break 
            for pos ,nmk in enumerate (keys ):
                if pick is None and len (nmk )>=3 and nmk in low :
                    pick =(1 ,pos ,col )
        if pick :
            roles [pick [2 ]]=role 
            used .add (pick [2 ])
    return roles 


def canonical_name (celltext ,synmap ):
    blob =str (celltext or "").strip ()
    nmk =key_form (blob )
    if nmk in synmap :
        return synmap [nmk ]
    col =blob .replace (" ","")
    if col .lower ()in synmap :
        return synmap [col .lower ()]
    return col if re .search (r"\d",col )and re .fullmatch (r"[A-Za-z0-9().\-]+",col )else blob 


def build_records (tab ,roles ,condcols ,msyn ,isyn ,res ):
    recs ,counter ,getrole =[],{},lambda rec :next ((col for col ,x in roles .items ()if x ==rec ),None )
    for pos ,orig in enumerate (tab ["rows"]):
        rowid =str (orig .get (getrole ("row_id"),"")).strip ()if getrole ("row_id")else ""
        if not rowid :
            rowid ="derived-%d"%(pos +1 )
            res ["degradations"].append ({"stage":"identity","file":tab ["file"].name ,"index":pos +1 ,
            "note":"row id missing -> derived (R002)"})
        elif rowid in counter :
            counter [rowid ]+=1 
            res ["degradations"].append ({"stage":"identity","file":tab ["file"].name ,"row_id":rowid ,
            "note":"repeated row id -> suffix #%d (R002)"%counter [rowid ]})
            rowid ="%s#%d"%(rowid ,counter [rowid ])
        else :
            counter [rowid ]=1 
        indicator =str (orig .get (getrole ("indicator"),"")).strip ()
        basename ,unitpart =split_unit_header (indicator )
        condmap ={col :str (orig .get (col ,"")).strip ()for col in condcols }
        recs .append ({"row_id":rowid ,"source_document_id":str (orig .get (getrole ("source_document_id"),"")).strip (),
        "source_locator":str (orig .get (getrole ("source_locator"),"")).strip (),
        "material":canonical_name (orig .get (getrole ("material"),""),msyn ),"indicator":canonical_name (basename or indicator ,isyn ),
        "conds":condmap ,"condition_summary":"; ".join ("%s=%s"%kv for kv in sorted (condmap .items ())if kv [1 ]),
        "value_raw":str (orig .get (getrole ("value"),"")).strip (),
        "unit_raw":str (orig .get (getrole ("unit"),"")).strip ()or unitpart ,"original_field":indicator })
    return recs 


def form_row (row ,unitlist ):
    """单行清洗入口：返回 (清洗后行, 变更条目, 待确认条目, 不确定项)。"""
    deltas ,holds ,doubts ,used_rules =[],[],[],set ()
    cellraw ,unitraw =row ["value_raw"],row ["unit_raw"]
    cell =parse_cell (cellraw )
    unitlabel =unitraw .strip ()or cell .get ("unit","").strip ()
    if not unitraw .strip ()and cell .get ("unit"):
        used_rules .add ("R004")
    condkey ="|".join ("%s=%s"%(key_form (nmk ),key_form (val ))for nmk ,val in sorted (row ["conds"].items ())if str (val ).strip ())
    shiftv ={"row_id":row ["row_id"],"source_document_id":row ["source_document_id"],
    "source_locator":row ["source_locator"],"indicator":row ["indicator"],"material":row ["material"],
    "condition_summary":row ["condition_summary"],"value":None ,"value_low":None ,
    "value_high":None ,"value_err":None ,"value_text":"","unit":"",
    "original_field":row ["original_field"],"original_value":cellraw ,"original_unit":unitraw ,
    "rule_ids":"","status":"ok","duplicate_of":"","note":"","_conds":row ["conds"],
    "judgment_key":"|".join ([row ["source_document_id"]or "-",condkey or "-",
    key_form (row ["indicator"])or "-",key_form (row ["material"])or "-"])}

    def pend (code ,reason ,action ,colname ="unit"):
        holds .append ({"row_id":shiftv ["row_id"],"field":colname ,"reason_code":code ,"reason":reason ,
        "suggested_action":action ,"original_value":cellraw ,"original_unit":unitraw or unitlabel ,
        "source_document_id":row ["source_document_id"],"source_locator":row ["source_locator"]})
        doubts .append ({"type":code ,"row_id":shiftv ["row_id"],"detail":"%s %s"%(cellraw ,unitlabel ),"action":"pending"})

    if cell ["kind"]=="missing":
        shiftv .update (status ="missing",value_text ="(missing: %s)"%cellraw .strip (),rule_ids ="R006")
        return shiftv ,deltas ,holds ,doubts 
    if cell ["kind"]=="text":
        shiftv .update (status ="needs_review",value_text =cellraw .strip (),rule_ids ="R006;R010")
        pend ("unparsed_value","cell is neither a number, a range nor a +/- value",
        "enter the numeric value or missing code from source","value")
        return shiftv ,deltas ,holds ,doubts 
    if not unitlabel :
        shiftv .update (status ="needs_review",value_text ="%s (no unit)"%cell .get ("raw",""),rule_ids ="R011")
        pend ("missing_unit","numeric value without a unit; conversion and comparison unsafe",
        "confirm unit from the header or caption")
        return shiftv ,deltas ,holds ,doubts 
    conv =unitlist .to_canonical (unitlabel )
    if conv is None :
        shiftv .update (status ="needs_review",value_text ="%s %s"%(cell .get ("raw",""),unitlabel ),rule_ids ="R010")
        pend ("unknown_unit","unit not resolvable by the unit table (a.u./arb./unparsable)",
        "confirm unit; arbitrary units stay out of statistics")
        return shiftv ,deltas ,holds ,doubts 
    mult ,offs =conv ["factor"],conv ["offset"]
    srcdec =len ((re .search (r"\.(\d+)",str (cellraw ))or ["",""])[1 ])
    shiftv ["unit"]=conv ["unit"]
    if cell ["kind"]=="range":
        targets ,used_rules =[("value_low",cell ["low"]),("value_high",cell ["high"])],used_rules |{"R007"}
    elif cell ["kind"]=="error":
        targets ,used_rules =[("value",cell ["value"]),("value_err",cell ["err"])],used_rules |{"R008"}
    else :
        targets =[("value",cell ["value"])]
    for colname ,orignum in targets :
        addterm =offs if colname !="value_err"else 0.0 
        newval =orignum *mult +addterm 
        shiftv [colname ]=abs (newval )if colname =="value_err"else newval 
        if abs (mult -1.0 )>1e-12 or abs (addterm )>1e-12 :
            formtext =("v*%s"%show_num (mult ,10 )if abs (mult -1.0 )>1e-12 else "v")+(
            (("+%s"if addterm >0 else "-%s")%show_num (abs (addterm ),10 ))if abs (addterm )>1e-12 else "")
            rowid ="R008"if colname =="value_err"else "R009"
            used_rules .add (rowid )
            deltas .append ({"row_id":shiftv ["row_id"],"field":colname ,"before":show_num (orignum ),"after":show_num (newval ),
            "unit_before":unitlabel ,"unit_after":conv ["unit"],"factor":show_num (mult ,10 ),
            "offset":show_num (addterm ,10 ),"formula":formtext ,"precision":"src_decimals=%d"%srcdec ,
            "rule_id":rowid ,"source_document_id":row ["source_document_id"],
            "source_locator":row ["source_locator"],
            "note":"range bound converted separately (R007)"if cell ["kind"]=="range"else ""})
        else :
            shiftv ["note"]=(shiftv ["note"]+" same_unit").strip ()
    if cell ["kind"]=="range":
        shiftv ["value_text"]="%s-%s"%(show_num (cell ["low"]),show_num (cell ["high"]))
    elif cell ["kind"]=="error":
        shiftv ["value_text"]="%s +/- %s"%(show_num (cell ["value"]),show_num (cell ["err"]))
    else :
        shiftv ["value_text"]=show_num (cell ["value"])
    if cell .get ("ineq"):
        shiftv ["note"]=(shiftv ["note"]+" ineq=%s"%cell ["ineq"]).strip ()
        doubts .append ({"type":"inequality","row_id":shiftv ["row_id"],"detail":cell ["ineq"]+str (cellraw ),
        "action":"note: bound"})
    shiftv ["rule_ids"]=";".join (sorted (used_rules ))
    return shiftv ,deltas ,holds ,doubts 


def value_spread (vlist ):
    cnt =[abs (val )for val in vlist if val is not None ]
    return 0.0 if len (cnt )<2 or not max (cnt )else (max (cnt )-min (cnt ))/max (cnt )


def find_duplicates (records ,lib ,res ):
    """完全重复合并；重复实验保留；数值冲突打标记并送人工清单。"""
    matchcfg =lib .get ("matching",{})
    conftol =float (matchcfg .get ("conflict_relative_tolerance",.05 ))
    reptol =float (matchcfg .get ("replicate_relative_tolerance",.05 ))
    buckets ,merged ,clashes ={},[],[]
    for rec in records :
        if rec ["status"]not in ("missing","needs_review"):
            buckets .setdefault (rec ["judgment_key"],[]).append (rec )
    for sig in sorted (buckets ):
        getrole =sorted (buckets [sig ],key=lambda x :natural_parts (x ["row_id"]))
        if len (getrole )<2 :
            continue 
        ids =[rec ["row_id"]for rec in getrole ]
        vlist =[rec ["value"]if rec ["value"]is not None else rec ["value_low"]for rec in getrole ]
        unitlist =sorted ({rec ["unit"]for rec in getrole })
        if len (unitlist )>1 :
            clashes .append ({"judgment_key":sig ,"row_ids":ids ,"kind":"unit_conflict",
            "values":[show_num (val )for val in vlist ],"reason":"same key, units %s"%unitlist })
            for rec in getrole :
                rec ["status"]="conflict"
            res ["uncertainties"].append ({"type":"source_conflict","row_id":ids [0 ],"action":"pending_review",
            "detail":"units differ inside one judgment key"})
            continue 
        identical =all (val is not None and abs (val -vlist [0 ])<=1e-9 *max (abs (val )for val in vlist )for val in vlist )
        disp =value_spread (vlist )
        if identical :
            for rec in getrole [1 :]:
                rec ["status"],rec ["duplicate_of"]="merged_duplicate",getrole [0 ]["row_id"]
            merged .append ({"judgment_key":sig ,"row_ids":ids ,"merged_row_ids":ids [1 :],"kept_row_id":ids [0 ],
            "action":"merge","reason":"identical source+condition+indicator+value (R013)"})
        elif disp <=reptol :
            for rec in getrole [1 :]:
                rec ["status"]="replicate"
            merged .append ({"judgment_key":sig ,"row_ids":ids ,"merged_row_ids":[],"kept_row_id":ids [0 ],
            "action":"keep_separate",
            "reason":"同键且离散度<=%.0f%%：属于重复实验，不是重复记录 (R014)"%(reptol *100 )})
        else :
            clashes .append ({"judgment_key":sig ,"row_ids":ids ,"kind":"value_conflict","unit":unitlist [0 ],
            "values":[show_num (val )for val in vlist ],
            "reason":"同来源同条件离散度 %.0f%% 超过 %.0f%%：换算无法裁决 (R015)"
            %(disp *100 ,conftol *100 )})
            for rec in getrole :
                rec ["status"]="conflict"
            res ["uncertainties"].append ({"type":"source_conflict","row_id":ids [0 ],
            "detail":"values %s %s"%([show_num (val )for val in vlist ],unitlist [0 ]),
            "action":"pending_review"})
    return merged ,clashes 


def tally_rules (deltas ,holds ):
    recs ={}
    entries =[(col ["rule_id"],"%s:%s %s->%s"%(col ["row_id"],col ["field"],col ["before"],col ["after"]))for col in deltas ]
    entries +=[({"unknown_unit":"R010","missing_unit":"R011","unparsed_value":"R006"}.get (prs ["reason_code"]),
    "%s:%s"%(prs ["row_id"],prs ["reason_code"]))for prs in holds ]# 待确认原因回映射到规则号
    for rowid ,powv in entries :
        if rowid :
            ent =recs .setdefault (rowid ,{"count":0 ,"examples":[]})
            ent ["count"]+=1 
            if len (ent ["examples"])<3 :
                ent ["examples"].append (powv )
    return recs 


def build_claims (deltas ,holds ,records ,rg ,cap ,body ):
    W ,recs =body .get ("claim",{}),[]

    def emit (nature ,readmode ,sent ,srctext ,rowid ,sid ,where ,condkey =""):
        if len (recs )<cap :
            recs .append ({"claim_id":"C%04d"%(len (recs )+1 ),"kind":nature ,"readability":readmode ,
            "statement":sent ,"evidence":{"quote":srctext ,"rule_id":rowid },"source_id":sid ,
            "location":where ,"condition":condkey })

    for col in deltas [:int (cap *.7 )]:
        emit ("inferred","inferred",W .get ("converted","")%(col ["row_id"],col ["field"],col ["before"],
        col ["unit_before"],col ["rule_id"],col ["after"],col ["unit_after"]),"%s %s"%(col ["before"],col ["unit_before"]),
        col ["rule_id"],col ["source_document_id"],{"row_id":col ["row_id"],"field":col ["field"],
        "source_locator":col ["source_locator"]})
    for prs in holds [:int (cap *.2 )]:
        emit ("undetermined","undetermined",W .get ("pending","")%(prs ["row_id"],prs ["field"],prs ["reason_code"]),
        "%s %s"%(prs ["original_value"],prs ["original_unit"]or ""),"R010",prs ["source_document_id"],
        {"row_id":prs ["row_id"],"field":prs ["field"],"source_locator":prs ["source_locator"]})
    emit ("reported","directly_read",W .get ("counts","")%(rg ["input_rows"],rg ["cleaned_rows"],
    rg ["analytic_rows"],rg ["merged_duplicates"],rg ["conflicts"],rg ["pending_review"]),"","","",
    {"file":"cleaned.csv"})
    return recs 
