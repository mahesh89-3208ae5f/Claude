"""下载逐秒 K 线(可断点续传),合并成 <币种>_1s.json,例如 btcusdt_1s.json。
用法: python3 fetch_1s.py [天数,默认 60] [币种,默认 BTCUSDT]   需要系统里有 curl。"""
import json,subprocess,sys,time,os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
SYM=(sys.argv[2] if len(sys.argv)>2 else "BTCUSDT").upper()
CH="chunks_"+SYM.lower(); OUT=SYM.lower()+"_1s.json"
os.makedirs(CH,exist_ok=True)
from concurrent.futures import ThreadPoolExecutor
DAYS=int(sys.argv[1]) if len(sys.argv)>1 else 60
end=(int(time.time())-60)//3000*3000*1000  # 对齐到 5 分钟窗口
start=end-DAYS*86400*1000
def get(t):
    fn=f"{CH}/{t}.json"
    if os.path.exists(fn): return
    url=f"https://data-api.binance.vision/api/v3/klines?symbol={SYM}&interval=1s&startTime={t}&endTime={t+999000}&limit=1000"
    for a in range(7):
        r=subprocess.run(["curl","-sS","-m","40",url],capture_output=True,text=True)
        try:
            d=json.loads(r.stdout); assert isinstance(d,list) and len(d)==1000 and d[0][0]==t
            json.dump([[float(x[1]) for x in d],[float(x[4]) for x in d]],open(fn+".tmp","w")); os.rename(fn+".tmp",fn); return
        except Exception: time.sleep(2**a)
    print("fail",t,r.stdout[:150],flush=True)
ts=list(range(start,end,1000000))[::-1]
with ThreadPoolExecutor(40) as ex: list(ex.map(get,ts))
fs=sorted(t for t in ts if os.path.exists(f"{CH}/{t}.json"))
assert len(fs)==len(ts),"有分块下载失败,请重新运行"
op=[];cl=[]
for t in fs:
    a,b=json.load(open(f"{CH}/{t}.json")); op+=a; cl+=b
n=(end-start)//1000; op=op[:n]; cl=cl[:n]
json.dump({"start":fs[0],"op":op,"cl":cl},open(OUT,"w"))
print("done",len(op),"seconds ->",os.path.abspath(OUT),flush=True)
