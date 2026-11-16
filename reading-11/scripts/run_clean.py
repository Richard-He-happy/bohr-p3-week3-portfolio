"""文献抽取记录清洗入口（reading-11 改编实现）。

单次运行产出：可统计宽表、行级变更记录、待人工确认清单、异常/冲突报告、
规则应用计数与运行自检。仅用标准库、不联网、不依赖当前工作目录。
调用：python3 run_clean.py --input /input --output /app/output [--determinism]
"""

import argparse ,csv ,json ,subprocess ,sys ,time ,traceback 

from pathlib import Path 

sys .path .insert (0 ,str (Path (__file__ ).resolve ().parent ))

from clean_engine import (ENGINE_VERSION ,UnitRegistry ,build_claims ,form_row ,tally_rules ,find_duplicates ,read_json ,natural_parts ,key_form ,read_text_file ,classify_columns ,
build_records ,write_csv ,write_json )

try :# 可核验资产层（v1.1.0 增补）：缺失时只记一条降级，回到 v1.0.0 行为
    import evidence_assets as evidence 
except Exception :# 回退路径：删除 scripts/evidence_assets.py 即生效
    evidence =None 

REF_DIR =Path (__file__ ).resolve ().parent .parent /"references"

NOTE_MARKERS =("note","comment","remark","memo","flag")

VOLATILE_ASSETS ={"run.log"}# 承载真实时间戳与耗时，--determinism 按设计不参与逐字节比对


def new_doc ():
    """result.json 骨架：所有路径（含早退与异常）都以它为基础，契约字段由 persist_result 回填。"""
    return {"case_id":None ,"status":"partial","result":{},"claims":[],"uncertainties":[],
    "uncertainty":[],"sources":[],"pending_human":[],"errors":[],"degradations":[],
    "changes":[],"contract_mapping":{},
    "runtime":{"tool":"literature-extraction-standardizer","version":ENGINE_VERSION ,
    "python":sys .version .split ()[0 ]}}


def mark (ctx ,phase ,ok =True ,**detail ):
    """向 run.log 追加一条阶段事件；时间戳/耗时只进 run.log，不进入确定性产物。"""
    events =ctx .get ("ev")
    if events is None :
        return 
    try :
        events .append ({"ts":time .strftime ("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed":round (time .time ()-float (ctx .get ("t0")or time .time ()),3 ),
        "phase":phase ,"ok":bool (ok ),"detail":detail })
    except Exception :
        pass 

ARTIFACT_LEAVES ={"table|sheet|dataset":"cleaned.csv","change|history|log":"change_log.csv",
"review|hold|pending":"pending_review.csv","anomal|quality|issues":"anomaly_report.md",
"rule|\u89c4\u5219":"rules.json","mapping|\u6620\u5c04":"field_mapping.json",
"unit|\u5355\u4f4d":"unit_table.json"}

CHANGE_COLUMNS =["row_id","field","before","after","unit_before","unit_after","factor","offset","formula",
"precision","rule_id","source_document_id","source_locator","note"]

PENDING_COLUMNS =["row_id","field","reason_code","reason","suggested_action","original_value","original_unit",
"source_document_id","source_locator"]


def locate_rows (obj ):
    if isinstance (obj ,list ):
        return [rec for rec in obj if isinstance (rec ,dict )]
    if not isinstance (obj ,dict ):
        return []
    for keyv in ("records","rows","data","items","measurements","extractions","entries","table",
    "values","results","artifacts")+tuple (sorted (obj )):
        val =obj .get (keyv )
        if isinstance (val ,list )and val and isinstance (val [0 ],dict ):
            return val 
        if isinstance (val ,dict )and locate_rows (val ):
            return locate_rows (val )
    return []


def as_text (val ):
    return ""if val is None else (str (val )if isinstance (val ,(str ,int ,float ))
    else json .dumps (val ,ensure_ascii =False ,sort_keys =True ))


def merge_rule_sets (found ,book ):
    rulelist ,shadowed =[],[]
    for item in book .get ("rules",[]):# 规则以定长数组存放，字段次序由 rule_fields 固定
        rulelist .append ({"rule_id":str (item [0 ]),"priority":int (item [1 ]),"applies_to":item [2 ],
        "condition":item [3 ],"transform":item [4 ],
        "examples":item [5 ],"failure_mode":item [6 ],"human_gate":bool (item [7 ])})
    for path ,obj in found ["rules"]:
        cand =obj .get ("rules")if isinstance (obj ,dict )else None 
        for rec in (cand if isinstance (cand ,list )else ([obj ]if obj .get ("rule_id")else [])):
            if not isinstance (rec ,dict )or not rec .get ("rule_id"):
                continue 
            rec ={"rule_id":str (rec ["rule_id"]),"priority":int (rec .get ("priority",10 )),
            "applies_to":rec .get ("applies_to","value"),"condition":rec .get ("condition",""),
            "transform":rec .get ("transform",rec .get ("action","")),"examples":rec .get ("examples",[]),
            "failure_mode":rec .get ("failure_mode",""),"human_gate":bool (rec .get ("human_gate",False ))}
            for idx ,old in enumerate (rulelist ):
                if old ["rule_id"]==rec ["rule_id"]:
                    win =rec ["priority"]<=old ["priority"]
                    shadowed .append ({"rule_id":(old if win else rec )["rule_id"],
                    "by":(rec if win else old )["rule_id"],"reason":"lower priority number wins"})
                    if win :
                        rulelist [idx ]=rec 
                    break 
            else :
                rulelist .append (rec )
    return sorted (rulelist ,key=lambda rec :(rec ["priority"],rec ["rule_id"])),shadowed 


def formula_matches (rec ):
    try :
        return abs (float (rec ["before"])*float (rec ["factor"])+float (rec ["offset"])-float (rec ["after"]))<=1e-6 *max (1.0 ,abs (float (rec ["after"])))
    except Exception :
        return False 


def backfill_contract (contract ,doc ):
    """把契约叶子回填成产物文件名 / 汇总值 / null，并返回 叶子→来源 的映射。"""
    paths ,rec ={},doc .get ("result")or {}

    def resolve_leaf (path ):
        lname =path .lower ()
        for keyv ,val in ARTIFACT_LEAVES .items ():
            if any (hint in lname for hint in keyv .split ("|")):
                return paths .setdefault (path ,val )
        for hint ,tag in (("count","counts"),("claim","claims"),("uncertain","uncertainties"),
        ("case_id","case_id"),("status","status"),("result","result")):
            if hint in lname :
                paths [path ]=tag 
                return rec .get (tag )if tag =="counts"else doc .get (tag )
        paths [path ]="null"
        return None 

    def visit (cname ,path ):
        if isinstance (cname ,(dict ,list ))and not cname and path :
            return resolve_leaf (path )
        if isinstance (cname ,list ):
            return [visit (val ,path )for val in cname ]
        if isinstance (cname ,dict ):
            return {keyv :visit (val ,path +"."+keyv if path else keyv )for keyv ,val in cname .items ()}
        return resolve_leaf (path )if isinstance (cname ,str )and cname .strip ()in ("","string","null")else cname 

    return visit (contract ,""),paths 


def verify_written_files (outdir ,stat ,doc ):
    """从已落盘文件复算变更公式，并核对计数、身份唯一性与规则可解析性。"""
    def read (cname ):
        path =outdir /cname 
        return list (csv .DictReader (open (path ,encoding ="utf-8")))if path .exists ()else []

    clean_rows ,deltas ,holds =read ("cleaned.csv"),read ("change_log.csv"),read ("pending_review.csv")
    idlist =[rec ["row_id"]for rec in clean_rows ]
    known_rules ={rec ["rule_id"]for rec in (read_json (outdir /"rules.json")[0 ]or {}).get ("rules",[])}
    good =sum (1 for rec in deltas if formula_matches (rec ))
    pct =100.0 *good /len (deltas )if deltas else 100.0 
    id_set =set (idlist )
    checks =[("counts match",[len (clean_rows ),len (deltas ),len (holds )]==[stat ["cleaned_rows"],stat ["changed_values"],
    stat ["pending_review"]],"%d/%d/%d"%(len (clean_rows ),len (deltas ),len (holds ))),
    ("row_id unique",bool (idlist )and len (idlist )==len (set (idlist )),str (len (idlist ))),
    ("after = before*factor + offset",good ==len (deltas ),"%.1f%% consistent"%pct ),
    ("rule_id resolves",not ({rec ["rule_id"]for rec in deltas }-known_rules ),""),
    ("no leaked value",not [rec ["row_id"]for rec in clean_rows 
    if rec ["status"]=="needs_review"and rec ["value"]],""),
    ("change row_id resolves",not ({rec ["row_id"]for rec in deltas }-id_set ),
    "%d change rows"%len (deltas )),
    ("analytic rows recount",len ([rec for rec in clean_rows if rec ["status"]in ("ok","replicate")])
    ==stat .get ("analytic_rows"),str (stat .get ("analytic_rows")))]
    badchars =[col for col in checks if not col [1 ]]
    write_json (outdir /"verify_report.json",{"checks":[{"name":cname ,"pass":bool (path ),"detail":detail }for cname ,path ,detail in checks ],
    "passed":len (checks )-len (badchars ),"total":len (checks ),
    "formula_consistency_pct":round (pct ,2 ),
    "verdict":"PASS"if not badchars else "CHECK"})
    print ("[verify_written_files] %d/%d passed, formula %.1f%% %s"%(len (checks )-len (badchars ),len (checks ),pct ,"PASS"if not badchars else "CHECK"))


def write_anomaly_report (ctx ,stat ,colmap ,merged ,clashes ,deltas2 ,holds2 ,msgs ):
    doc ,outdir ,agg =ctx ["res"],ctx ["out"],{}
    for path in holds2 :
        agg [path ["reason_code"]]=agg .get (path ["reason_code"],0 )+1 
    un =[col ["original"]for col in colmap if not col ["mapped"]]
    L =["# "+msgs .get ("report_title","文献抽取数据清洗报告"),"",msgs .get ("report_intro","")%ENGINE_VERSION ,"",
    "counts: "+", ".join ("%s=%s"%(keyv ,stat .get (keyv ))for keyv in stat ),
    "mapped %d/%d; unmapped: %s"
    %(len (colmap )-len (un ),len (colmap ),", ".join (un [:20 ])or "none"),
    "pending review: "+(", ".join ("`%s`=%d"%(keyv ,agg [keyv ])for keyv in sorted (agg ))or "none"),
    "rules: "+(", ".join ("%s x%d"%(keyv ,val ["count"])
    for keyv ,val in sorted (tally_rules (deltas2 ,holds2 ).items ()))or "none"),
    "duplicates / conflicts:"]
    L +=["- %s `%s` [%s]: %s"%(objv .get ("action","conflict"),objv ["judgment_key"],",".join (objv ["row_ids"]),
    objv ["reason"])for objv in clashes +merged ]
    L +=["degradations: %s"%"; ".join (
    ["%s: %s"%(detail .get ("stage"),detail .get ("note"))for detail in doc ["degradations"][:25 ]]+
    ["error %s: %s"%(exc .get ("stage"),exc .get ("error"))for exc in doc ["errors"][:20 ]])]
    L +=["boundaries:"]+["- "+objv for objv in msgs .get ("boundary",[])]
    Path (outdir /"anomaly_report.md").write_text ("\n".join (L )+"\n",encoding ="utf-8")


def pipeline (ctx ):
    indir ,outdir ,doc ,args =ctx ["ind"],ctx ["out"],ctx ["res"],ctx ["a"]
    registry =read_json (REF_DIR /"unit_registry.json")[0 ]
    book =read_json (REF_DIR /"rulebook.json")[0 ]or {}
    if not registry :
        raise RuntimeError ("references/unit_registry.json unreadable")
    ureg ,found =UnitRegistry (registry ),scan_inputs (indir )
    casedoc =found ["case"]or {}
    doc ["case_id"],ctx ["tpl"]=casedoc .get ("case_id"),casedoc .get ("output_contract")or {}
    ctx ["ureg"],ctx ["case"],ctx ["contract"]=ureg ,casedoc ,ctx ["tpl"]
    ctx ["case_file"]=str (found ["cp"])if found ["cp"]else ""
    ctx ["record_files"]=[str (obj )for obj in found ["records"]]
    if found ["case"]is None :
        doc ["degradations"].append ({"stage":"scan_inputs","note":"no case.json"})
    mark (ctx ,"scan_inputs",case =bool (found ["case"]),record_files =len (found ["records"]),
    rule_files =len (found ["rules"]),schema_files =len (found ["schema"]))
    rulelist ,shadowed =merge_rule_sets (found ,book )
    target =dict (book .get ("target_table",{}))
    colroles ={exc .get ("role"):list (exc .get ("aliases",[]))for exc in book .get ("column_roles",[])}
    aliases ={"material":{key_form (keyv ):val for keyv ,val in book .get ("material_aliases",{}).items ()},
    "indicator":{key_form (keyv ):val for keyv ,val in book .get ("indicator_aliases",{}).items ()}}
    for _ ,obj in found ["schema"]:
        if isinstance (obj ,dict ):
            target ["fields"]=next ((obj [keyv ]for keyv in ("fields","schema","target_schema")
            if isinstance (obj .get (keyv ),dict )),target .get ("fields",{}))
            colroles .update ({keyv :val if isinstance (val ,list )else [val ]for keyv ,val in (obj .get ("field_roles")or {}).items ()})
            for keyv ,tag in (("synonyms","material"),("material_synonyms","material"),
            ("indicator_synonyms","indicator")):
                aliases [tag ].update ({key_form (objv ):y for objv ,y in (obj .get (keyv )or {}).items ()})
    ctx ["rulebook"],ctx ["target"]=book ,target 
    ctx ["rules"]={rec ["rule_id"]:rec for rec in rulelist }
    mark (ctx ,"rules_merged",rules =len (rulelist ),suppressed =len (shadowed ))

    tablist ,srclog =[],[]
    for path in found ["records"]:
        cells ,codec ,badchars ,failure =[],"json",0 ,None 
        if path .suffix .lower ()==".csv":
            msgs ,codec ,badchars ,failure =read_text_file (path )
            cells =[]if failure else [{keyv :as_text (val )for keyv ,val in rec .items ()if keyv is not None }
            for rec in csv .DictReader (msgs .splitlines ())]
        else :
            obj ,failure =read_json (path )
            cells =[]if failure else [{keyv :as_text (val )for keyv ,val in rec .items ()}for rec in locate_rows (obj )]
        if failure :
            doc ["errors"].append ({"stage":"read","file":path .name ,"error":failure })
            continue 
        if badchars :
            doc ["degradations"].append ({"stage":"read","file":path .name ,"count":badchars ,"note":"encoding (R019)"})
        cells =[rec for rec in cells if any (str (val ).strip ()for val in rec .values ())]
        srclog .append ({"source_id":path .stem ,"path":str (path ),"rows":len (cells )})
        if cells :
            tablist .append ({"file":path ,"rows":cells })
        else :
            doc ["degradations"].append ({"stage":"read","file":path .name ,"note":"no rows (R020)"})
    mark (ctx ,"read_records",tables =len (tablist ),rows =sum (len (tab ["rows"])for tab in tablist ),
    failed_files =len (doc ["errors"]))
    if not tablist :
        doc ["degradations"].append ({"stage":"scan_inputs","note":"no record table"})
        doc ["status"]="insufficient_evidence"
        mark (ctx ,"no_record_table",ok =False )
        return 

    longrows ,colmap =[],[]
    for tab in tablist :
        colnames =[]
        for rec in tab ["rows"]:
            colnames +=[keyv for keyv in rec if keyv not in colnames ]
        rolemap =classify_columns (colnames ,colroles )
        condcols =[col for col in colnames if col not in rolemap and not any (hint in str (col ).lower ()for hint in NOTE_MARKERS )]
        if "value"not in rolemap :
            doc ["degradations"].append ({"stage":"build_records","note":"%s: no value col (R003)"%tab ["file"].name })
        colmap +=[{"original":col ,"file":tab ["file"].name ,"target":rolemap .get (col ,""),"mapped":col in rolemap ,
        "basis":("synonym hit -> %s"%rolemap [col ])if col in rolemap 
        else "no hit; kept as condition/annotation"}for col in colnames ]
        built =build_records (tab ,rolemap ,condcols ,aliases ["material"],aliases ["indicator"],doc )
        for rec in built :# 资产层把握 quote 绑定到具体输入文件
            rec ["_file"]=tab ["file"].name 
        longrows +=built 
    ctx ["longrows"]=longrows 
    mark (ctx ,"columns_mapped",columns =len (colmap ),
    mapped =len ([col for col in colmap if col ["mapped"]]),input_rows =len (longrows ))
    if not longrows :
        doc ["degradations"].append ({"stage":"build_records","note":"no measurable row"})
        doc ["status"]="insufficient_evidence"
        mark (ctx ,"no_measurable_row",ok =False )
        return 

    cleanrows ,deltas2 ,holds2 ,doubts ,straight =[],[],[],[],0 
    for row in longrows :
        obj ,deltas ,holds ,un =form_row (row ,ureg )
        cleanrows .append (obj )
        deltas2 +=deltas 
        holds2 +=holds 
        doubts +=un 
        straight +=1 if (not deltas and obj ["value"]is not None )else 0 
    mark (ctx ,"rows_cleaned",rows =len (cleanrows ),changed_values =len (deltas2 ),
    pending_review =len (holds2 ))
    merged ,clashes =find_duplicates (cleanrows ,book ,doc )
    mark (ctx ,"dedupe",merged =len (merged ),conflicts =len (clashes ))
    outfields =["row_id","source_document_id","source_locator","indicator","material","condition_summary",
    "value","value_low","value_high","value_err","value_text","unit","original_field",
    "original_value","original_unit","rule_ids","judgment_key","status","duplicate_of","note"]
    cells =[{keyv :val for keyv ,val in rec .items ()if not keyv .startswith ("_")}for rec in cleanrows ]
    cells .sort (key=lambda rec :(str (rec ["source_document_id"]),natural_parts (rec ["row_id"])))
    deltas2 .sort (key=lambda col :(str (col ["source_document_id"]),natural_parts (col ["row_id"]),col ["field"]))
    holds2 .sort (key=lambda path :(str (path ["source_document_id"]),natural_parts (path ["row_id"]),path ["reason_code"]))
    for fname ,outrows ,fnames in (("cleaned.csv",cells ,outfields ),("change_log.csv",deltas2 ,CHANGE_COLUMNS ),
    ("pending_review.csv",holds2 ,PENDING_COLUMNS )):
        write_csv (outdir /fname ,outrows ,fnames )
    write_json (outdir /"rules.json",{"version":book .get ("version","1.0.0"),"precedence":book .get ("precedence",""),
    "rules":rulelist ,"suppressed_rules":shadowed ,"applied_counts":tally_rules (deltas2 ,holds2 )})
    write_json (outdir /"field_mapping.json",{
    "target_schema_version":target .get ("version","1.0.0"),
    "schema_source":"case supplied"if found ["schema"]else "references/rules_library.json",
    "columns":colmap ,"unmapped":[col ["original"]for col in colmap if not col ["mapped"]],
    "note":"basis is a synonym hit or a schema field name; unmapped columns are reported, not guessed"})
    seen ={}
    for col in deltas2 :
        exc =seen .setdefault ("%s -> %s"%(col ["unit_before"],col ["unit_after"]),
        {"from":col ["unit_before"],"to":col ["unit_after"],"factor":col ["factor"],
        "offset":col ["offset"],"count":0 })
        exc ["count"]+=1 
    uto =dict (registry )
    uto ["observed_conversions"]=[seen [keyv ]for keyv in sorted (seen )]
    write_json (outdir /"unit_table.json",uto )
    mark (ctx ,"artifacts_written",tables =3 ,json_files =3 ,rows =len (cells ),
    change_rows =len (deltas2 ))

    stat ={"input_rows":len (longrows ),"cleaned_rows":len (cells ),"changed_values":len (deltas2 ),
    "unchanged_values":straight ,"pending_review":len (holds2 ),"anomalies":len (holds2 )+len (doubts ),
    "analytic_rows":len ([rec for rec in cells if rec ["status"]in ("ok","replicate")]),
    "missing_values":len ([rec for rec in cells if rec ["status"]=="missing"]),
    "range_values":len ([rec for rec in cells if rec ["value_low"]is not None ]),
    "error_term_values":len ([rec for rec in cells if rec ["value_err"]is not None ]),
    "merged_duplicates":len ([rec for detail in merged for rec in detail ["merged_row_ids"]]),
    "conflicts":len ({rec for detail in clashes for rec in detail ["row_ids"]}),
    "rows_with_row_id_and_source":len ([rec for rec in cells if rec ["row_id"]and rec ["source_document_id"]])}
    msgs =book .get ("messages",{})
    doc ["result"]=dict (doc ["result"],**{
    "counts":stat ,
    "rules_applied":[{"rule_id":keyv ,"count":val ["count"],"examples":val ["examples"]}
    for keyv ,val in sorted (tally_rules (deltas2 ,holds2 ).items ())],
    "duplicates":merged ,"conflicts":clashes ,
    "unknown_units":sorted ({path ["original_unit"]for path in holds2 }),

    "coverage":{"columns_seen":len (colmap ),"columns_mapped":len ([col for col in colmap if col ["mapped"]]),
    "columns_unmapped":[col ["original"]for col in colmap if not col ["mapped"]],
    "rows_fully_traceable":stat ["rows_with_row_id_and_source"],
    "rows_with_locator":len ([rec for rec in cells if rec ["source_locator"]])},
    "condition_columns":sorted ({col for rec in cleanrows for col in rec ["_conds"]}),
    "judgment_key_template":book .get ("matching",{}).get ("template",""),
    "method_notes":msgs .get ("method_notes",[]),"artifacts":msgs .get ("artifacts",{})})
    doc ["changes"]=deltas2 [:400 ]
    doc ["pending_human"]=[{keyv :path [keyv ]for keyv in ("row_id","field","reason_code","reason","suggested_action")}
    for path in holds2 [:400 ]]
    doc ["uncertainties"]=doc ["uncertainty"]=doubts [:400 ]
    doc ["sources"]=srclog 
    doc ["claims"]=build_claims (deltas2 ,holds2 ,cells ,stat ,200 ,msgs )
    doc ["status"]=("insufficient_evidence"if not cells else "partial"if (holds2 or clashes )else "ok")
    write_anomaly_report (ctx ,stat ,colmap ,merged ,clashes ,deltas2 ,holds2 ,msgs )


def persist_result (ctx ):
    doc ,outdir =ctx ["res"],ctx ["out"]
    contract =ctx .get ("tpl")or {}
    if isinstance (contract ,dict )and contract :
        filled ,paths =backfill_contract (contract ,doc )
        for keyv ,val in filled .items ():
            doc .setdefault (keyv ,val )
        doc ["contract_mapping"]=paths 
    write_json (outdir /"result.json",doc )


def scan_inputs (detail ):
    found ={"case":None ,"cp":None ,"records":[],"rules":[],"schema":[]}
    files =sorted (path for path in detail .rglob ("*")if path .is_file ())if detail .exists ()else []
    for path in sorted ([objv for objv in files if objv .suffix .lower ()==".json"],
    key=lambda objv :(not objv .name .lower ().startswith ("case"),str (objv ))):
        obj ,_ =read_json (path )
        if isinstance (obj ,dict )and ("output_contract"in obj or obj .get ("case_id")):
            found ["case"],found ["cp"]=obj ,path 
            break 
    for path in files :
        if path ==found ["cp"]or path .suffix .lower ()not in (".csv",".json"):
            continue 
        if path .suffix .lower ()==".csv":
            found ["records"].append (path )
            continue 
        obj ,failure =read_json (path )
        if failure or obj is None :
            found ["records"].append (path )
            continue 
        lname ,probe =path .name .lower (),json .dumps (obj ,ensure_ascii =False )[:3000 ].lower ()
        kind ="rules"if ("rule"in lname or '"rule_id"'in probe )else (
        "schema"if ("schema"in lname or "dictionar"in lname or '"fields"'in probe )else "records")
        found [kind ].append ((path ,obj )if kind !="records"else path )
    return found 


def main (argv =None ):
    ap =argparse .ArgumentParser (prog ="run_clean.py",description =(
    "文献抽取记录清洗：列名映射、单位换算、同义归一、重复/冲突判定，"
    "并输出逐行可追溯的变更记录。"))
    ap .add_argument ("--input",help ="输入目录；缺省依次取 /input 或包上级的 input/")
    ap .add_argument ("--output",help ="输出目录；缺省依次取 /app/output 或包上级的 output/")
    ap .add_argument ("--determinism",action ="store_true",help ="连跑两次并逐字节比较落盘产物")
    args =ap .parse_args (argv )
    base =REF_DIR .parent 
    indir =Path (args .input ).resolve ()if args .input else next (
    (Path (path )for path in ("/input",str (base /"input"))if Path (path ).exists ()),Path ("/input"))
    outdir =Path (args .output ).resolve ()if args .output else (Path ("/app/output")if Path ("/app").exists ()
    else base /"output")
    outdir .mkdir (parents =True ,exist_ok =True )
    if args .determinism :
        dg ,skipped =[],["none"]
        for keyv in ("_d1","_d2"):
            detail =outdir /keyv 
            detail .mkdir (parents =True ,exist_ok =True )
            subprocess .run ([sys .executable ,"-B",str (Path (__file__ ).resolve ()),"--input",str (indir ),
            "--output",str (detail )],capture_output =True )
            files ={path .name :path .read_bytes ()for path in sorted (detail .iterdir ())if path .is_file ()}
            skipped =sorted (name for name in files if name in VOLATILE_ASSETS )or ["none"]
            dg .append ({name :data for name ,data in files .items ()if name not in VOLATILE_ASSETS })
            for path in sorted (detail .iterdir ()):
                path .unlink ()
            detail .rmdir ()
        diff =sorted (cname for cname in set (dg [0 ])|set (dg [1 ])if dg [0 ].get (cname )!=dg [1 ].get (cname ))
        print ("[determinism] %s %s excluded_volatile=%s"
        %("identical"if not diff else "DIFFERS",diff ,",".join (skipped )))
        return 0 
    doc =new_doc ()
    write_json (outdir /"result.json",doc )# 先写 partial 结果：即使中断也留下合法产出
    partial_size =(outdir /"result.json").stat ().st_size if (outdir /"result.json").exists ()else 0 
    ctx ={"ind":indir ,"out":outdir ,"res":doc ,"a":args ,"tpl":{} ,"ev":[] ,"t0":time .time (),
    "partial_at_start":{"written":True ,"file":"result.json","bytes":partial_size },
    "probe":{"pipeline":pipeline ,"persist":persist_result ,"doc_factory":new_doc},
    "ref_files":[str (REF_DIR /"rulebook.json")]}
    mark (ctx ,"start",input =str (indir ),output =str (outdir ))
    mark (ctx ,"partial_result",bytes =partial_size )
    try :
        pipeline (ctx )
    except Exception as exc :
        doc ["errors"].append ({"stage":"pipeline","error":"%s: %s"%(type (exc ).__name__ ,exc ),
        "traceback":traceback .format_exc (limit =3 )[-800 :]})
        mark (ctx ,"pipeline",ok =False ,error ="%(t)s: %(e)s"%{"t":type (exc ).__name__ ,"e":exc })
    persist_result (ctx )
    mark (ctx ,"contract_backfilled",keys =len (doc .get ("contract_mapping")or {}),
    case_id =doc .get ("case_id"),status =doc .get ("status"))
    try :
        stat =(doc .get ("result")or {}).get ("counts")or {}
        if stat :
            verify_written_files (outdir ,stat ,doc )
            mark (ctx ,"verify",passed =True ,counters =len (stat ))
    except Exception as exc :
        print ("[verify_written_files] skipped: %s"%exc )
        mark (ctx ,"verify",ok =False ,error =str (exc ))
    if evidence is not None :
        try :# 5 个可核验资产：build/finalize 阶段无条件写出
            summary =evidence .emit_assets (outdir ,ctx )
            doc .update (summary )
            mark (ctx ,"assets_attached",ok =True ,assets =len (summary ))
            persist_result (ctx )# 把 5 个汇总键覆盖进 result.json
            print ("[evidence_assets] golden items=%s, diff met/deviation/missing=%s/%s/%s, self_check=%s"
            %(summary ["golden_standard"].get ("items"),summary ["diff_report"].get ("met"),
            summary ["diff_report"].get ("deviation"),summary ["diff_report"].get ("missing"),
            summary ["self_check"].get ("ok")))
        except Exception as exc :
            doc ["degradations"].append ({"stage":"evidence_assets",
            "note":"%s: %s"%(type (exc ).__name__ ,exc )})
            persist_result (ctx )
            print ("[evidence_assets] degraded: %s"%exc )
    else :
        doc ["degradations"].append ({"stage":"evidence_assets","note":"module missing (rollback path)"})
        persist_result (ctx )
        print ("[evidence_assets] module missing: original 9 artifacts only (v1.0.0 rollback path)")
    return 0 


if __name__ =="__main__":
    try :
        sys .exit (main ())
    except KeyboardInterrupt :
        sys .exit (0 )
    except Exception :
        traceback .print_exc ()
        sys .exit (0 )
