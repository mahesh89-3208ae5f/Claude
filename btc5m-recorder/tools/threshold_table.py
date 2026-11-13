"""用逐秒数据重算门槛表。用法: python3 threshold_table.py [btc_1s.json]
输出每个(偏离分档, 剩余时间)格子的历史胜率 / 95% 置信下限 / 样本数,
以及保本收益率和最低要求收益率(下限再减 2 个点)。rules.py 里的 TABLE 取自
剩余 90 秒和 60 秒两列。还包含高/低波动分组、样本外检验和分时段统计。"""
import json,math,os,sys
f=sys.argv[1] if len(sys.argv)>1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),"btc_1s.json")
D=json.load(open(f))
if "rows" in D: op=[x[1] for x in D["rows"]]; cl=[x[2] for x in D["rows"]]
else: op=D["op"]; cl=D["cl"]
start=D["start"]; N=len(op); nw=N//300
def wil(k,n,z=1.96):
    if n==0: return 0
    p=k/n; d=1+z*z/n
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/d
# trailing 30-min vol per window (1s returns)
W=[]
for w in range(6,nw):
    i=w*300; o=op[i]; c=cl[i+299]
    s=0.0
    for j in range(i-1800,i,1):
        r=cl[j]/cl[j-1]-1; s+=r*r
    W.append((i,o,c,math.sqrt(s/1800)))
n=len(W); print("windows",n,"ties",sum(1 for i,o,c,s in W if c==o))
sig=sorted(s for *_,s in W); med=sig[n//2]
bins=[(0,0.01),(0.01,0.02),(0.02,0.04),(0.04,0.07),(0.07,0.10),(0.10,0.15),(0.15,0.25),(0.25,9)]
ts=[60,120,150,180,210,240,270]
def table(sel,label,show="p"):
    print("\n"+label); print("  dev%       "+"".join(f"   left{300-t:>4}s   " for t in ts))
    for lo,hi in bins:
        line=f"  {lo:.2f}-{hi:.2f} "
        for t in ts:
            ok=tot=0
            for i,o,c,s in W:
                if not sel(i,s): continue
                d=(cl[i+t-1]/o-1)*100
                if d!=0 and lo<=abs(d)<hi: tot+=1; ok+=(d>0)==(c>o) and c!=o
            if tot<40: line+="        -       "; continue
            p=ok/tot; l=wil(ok,tot)
            if show=="p": line+=f" {p:5.1%}/{l:5.1%}/{tot:<4d}"
            else:
                q=l-0.02; line+=f"  be{(1-p)/p:6.1%} min{(1-q)/q:6.1%}"
        print(line)
table(lambda i,s:True,"ALL: p / wilson95 lower / n")
table(lambda i,s:True,"ALL: breakeven return / min required return (lower bound - 2pts)",show="r")
table(lambda i,s:s<=med,"LOW VOL half: p/lower/n")
table(lambda i,s:s>med,"HIGH VOL half: p/lower/n")
# out-of-sample: fit first 2/3, test last 1/3
cut=W[int(n*2/3)][0]
fit={}
for lo,hi in bins:
    for t in ts:
        ok=tot=0
        for i,o,c,s in W:
            if i>=cut: break
            d=(cl[i+t-1]/o-1)*100
            if d!=0 and lo<=abs(d)<hi: tot+=1; ok+=(d>0)==(c>o) and c!=o
        fit[(lo,t)]=(ok/tot if tot>=40 else None)
B={}
for i,o,c,s in W:
    if i<cut: continue
    for lo,hi in bins:
        for t in ts:
            d=(cl[i+t-1]/o-1)*100
            p=fit[(lo,t)]
            if p and d!=0 and lo<=abs(d)<hi:
                b=min(int(p*20),19); a=B.setdefault(b,[0,0,0]); a[0]+=1;a[1]+=p;a[2]+=(d>0)==(c>o) and c!=o
print("\nOUT OF SAMPLE (fit first 2/3, test last 1/3)")
for b in sorted(B): a=B[b]; print(f"  table says {a[1]/a[0]:.1%}  actual {a[2]/a[0]:.1%}  n={a[0]}")
# by Beijing 4h block: share of windows reaching >=0.04% dev at left=120s
print("\nBeijing hour: windows/day with |dev|>=0.04% at 120s left, and p there")
H={}
for i,o,c,s in W:
    h=((start//1000+i)//3600+8)%24
    d=(cl[i+179]/o-1)*100; a=H.setdefault(h,[0,0,0]); a[0]+=1
    if abs(d)>=0.04: a[1]+=1; a[2]+=(d>0)==(c>o) and c!=o
for h in sorted(H): a=H[h]; print(f"  {h:02d}h share {a[1]/a[0]:.0%}  p {a[2]/max(a[1],1):.1%} n={a[1]}")
