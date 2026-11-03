#!/usr/bin/env bash
# catdock 应用图标生成：原图 -> 圆角方底图 + 苹果剪影 -> Android 自适应/各密度资源
# 用法：bash tools/make_icon.sh "<原图 1536x1536.png>"
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(realpath "$1")"
WORK="${WORK:-/tmp/catdock-icon}"; mkdir -p "$WORK"; cd "$WORK"
RES="${RES:-$SCRIPT_DIR/../app/src/main/res}"
N=1536

# ---------- 1. 苹果剪影掩膜 ----------
# 近白像素（min 通道 > 246）= 白环 + 外圈白边；洪水填充去掉与边框连通的白边，只剩白环
convert "$SRC" -depth 8 rgb:rgb.raw
python3 - <<'EOF'
N=1536
rgb=open('./rgb.raw','rb').read()
out=bytearray(N*N)
for i in range(0,N*N*3,3):
    m=rgb[i]
    if rgb[i+1]<m: m=rgb[i+1]
    if rgb[i+2]<m: m=rgb[i+2]
    out[i//3]=255 if m>246 else 0
open('./w.raw','wb').write(bytes(out))
EOF
convert -size ${N}x${N} -depth 8 gray:w.raw w.png
convert w.png -fuzz 0% -fill gray50 -draw "color 0,0 floodfill" wr.png
convert wr.png -threshold 60% ring.png
# 填洞：白环 + 环内果体 = 苹果
convert ring.png -negate -fuzz 0% -fill black -draw "color 0,0 floodfill" g.png
convert ring.png g.png -compose Lighten -composite -median 7 apple_m.png
convert apple_m.png -depth 8 -type Grayscale gray:apple_m.raw

# ---------- 2. 量出圆角方的真实边界与圆角 ----------
eval "$(python3 - <<'EOF'
N=1536
rgb=open('./rgb.raw','rb').read()
ap=open('./apple_m.raw','rb').read()
def mn(x,y):
    i=(y*N+x)*3; return min(rgb[i],rgb[i+1],rgb[i+2])
def nw(x,y): return mn(x,y)<245
row=col=N//2
L=next(x for x in range(N) if nw(x,row)); R=next(x for x in range(N-1,-1,-1) if nw(x,row))
T=next(y for y in range(N) if nw(col,y)); B=next(y for y in range(N-1,-1,-1) if nw(col,y))
w,h=R-L+1,B-T+1
side=max(w,h)
# 圆角：左上角沿行扫描内缩量，取 dy=r/2 处反解（圆角方近似圆）
r=None
for dy in range(4,300,4):
    xs=[x for x in range(L,L+400) if nw(x,T+dy)]
    if not xs: r=dy; break
    if xs[0]-L<=2: r=dy; break
print('SX=%d SY=%d SW=%d SH=%d SIDE=%d RAD=%d'%(L,T,w,h,side,r or 220))
# 苹果中心 -> 画布中心的平移（按同一裁剪/拉伸换算）
cols=[0]*N; rows=[0]*N
for y in range(N):
    b=y*N; c=0
    for x in range(N):
        if ap[b+x]>127: c+=1; cols[x]+=1
    rows[y]=c
cx=[i for i,v in enumerate(cols) if v>=20]; ry=[i for i,v in enumerate(rows) if v>=20]
acx,acy=(cx[0]+cx[-1])//2,(ry[0]+ry[-1])//2
print('ASHIFT_X=%d ASHIFT_Y=%d'%(side//2-(acx-L)*side//w, side//2-(acy-T)*side//h))
EOF
)"
echo "圆角方 ${SW}x${SH}+${SX}+${SY} -> 正方形 ${SIDE}，圆角 ${RAD}，苹果平移 ${ASHIFT_X},${ASHIFT_Y}"

# ---------- 3. 素材（统一到 SIDE 正方形，横纵向 2.4% 以内的拉伸忽略不计） ----------
CONV="${SW}x${SH}+${SX}+${SY}"
convert "$SRC" -crop "$CONV" +repage -resize "${SIDE}x${SIDE}!" sq_rgb.png
convert -size ${SIDE}x${SIDE} xc:black -fill white \
  -draw "roundrectangle 3,3,$((SIDE-4)),$((SIDE-4)),${RAD},${RAD}" -blur 0x1.5 sq_a.png
# 苹果掩膜同样裁剪+拉伸，再平移到正中
convert -size ${N}x${N} -depth 8 gray:apple_m.raw -crop "$CONV" +repage -resize "${SIDE}x${SIDE}!" \
  -roll "+${ASHIFT_X}+${ASHIFT_Y}" -blur 0x1.2 ap_a.png
convert sq_rgb.png sq_a.png -alpha off -compose CopyOpacity -composite -strip sq.png
convert sq_rgb.png ap_a.png -alpha off -compose CopyOpacity -composite -strip apple_art.png
identify -format "sq %wx%h  apple %wx%h\n" sq.png apple_art.png

# ---------- 3b. 背景底板：只用果体之外的像素拟合一次平面渐变 ----------
# 直接缩放原图会连苹果一起放大，自适应图层里出现重影；平面拟合同时保留原图的对角渐变方向
convert sq_a.png -depth 8 -type Grayscale gray:sa.raw
convert sq_rgb.png -depth 8 rgb:srgb.raw
python3 - <<'EOF'
N=1400
rgb=open('./srgb.raw','rb').read(); a=open('./sa.raw','rb').read()
xs=ys=ns=nxx=nxy=nyy=0.0
nr=[0.0]*3; ng=[0.0]*3; nb=[0.0]*3
for y in range(0,N,2):
    for x in range(0,N,2):
        if a[y*N+x]<240: continue
        i=(y*N+x)*3; mn=min(rgb[i],rgb[i+1],rgb[i+2])
        if mn>235: continue            # 外圈白边/阴影
        u,v=x/N,y/N
        xs+=u; ys+=v; ns+=1; nxx+=u*u; nxy+=u*v; nyy+=v*v
        nr[0]+=rgb[i]; nr[1]+=u*rgb[i]; nr[2]+=v*rgb[i]
        ng[0]+=rgb[i+1]; ng[1]+=u*rgb[i+1]; ng[2]+=v*rgb[i+1]
        nb[0]+=rgb[i+2]; nb[1]+=u*rgb[i+2]; nb[2]+=v*rgb[i+2]
M=[[ns,xs,ys],[xs,nxx,nxy],[ys,nxy,nyy]]
def solve(M,b):
    n=len(M); A=[r[:]+[b[i]] for i,r in enumerate(M)]
    for i in range(n):
        p=max(range(i,n),key=lambda r:abs(A[r][i])); A[i],A[p]=A[p],A[i]
        pv=A[i][i]
        for r in range(i+1,n):
            f=A[r][i]/pv
            for c in range(i,n+1): A[r][c]-=f*A[i][c]
    x=[0.0]*n
    for i in reversed(range(n)):
        x[i]=(A[i][n]-sum(A[i][j]*x[j] for j in range(i+1,n)))/A[i][i]
    return x
co=[solve([r[:] for r in M],nr),solve([r[:] for r in M],ng),solve([r[:] for r in M],nb)]
out=bytearray(N*N*3)
for y in range(N):
    for x in range(N):
        u,v=x/N,y/N
        i=(y*N+x)*3
        for k,c in enumerate(co):
            out[i+k]=max(0,min(255,int(c[0]+c[1]*u+c[2]*v+.5)))
open('./plate.rgb','wb').write(bytes(out))
for lbl,u,v in (('左上',0,0),('右上',1,0),('左下',0,1),('右下',1,1)):
    print(lbl,' '.join('#%02X%02X%02X'%tuple(max(0,min(255,int(co[k][0]+co[k][1]*u+co[k][2]*v+.5))) for k in range(3))))
EOF
convert -size ${SIDE}x${SIDE} -depth 8 rgb:plate.rgb -strip plate.png

# ---------- 4. 资源 ----------
for d in mdpi:48:108 hdpi:72:162 xhdpi:96:216 xxhdpi:144:324 xxxhdpi:192:432; do
  dens=${d%%:*}; rest=${d#*:}; legacy=${rest%%:*}; layer=${rest##*:}
  dir=$RES/mipmap-$dens
  mkdir -p "$dir"
  convert sq.png -resize "${legacy}x${legacy}" -strip "$dir/ic_launcher.png"
  convert sq.png -resize "${legacy}x${legacy}" \
    \( -size "${legacy}x${legacy}" xc:none -fill white -draw "circle $(($legacy/2)),$(($legacy/2)) $(($legacy/2)),0" \) \
    -alpha off -compose CopyOpacity -composite -strip "$dir/ic_launcher_round.png"
  # 自适应图层：原图的整个方幅对应可视 72dp 窗口，故底板放大 150% 再居中裁
  b=$(( layer * 150 / 100 ))
  convert plate.png -resize "${b}x${b}" -gravity center -crop "${layer}x${layer}+0+0" +repage -strip \
    "$dir/ic_launcher_background.png"
  # 苹果在原图里占方幅约 80%；自适应安全区为 66/108=61%，取 58% 尽量贴近原图又不越界
  convert -size "${layer}x${layer}" xc:none \
    \( apple_art.png -crop "$(convert apple_art.png -format '%@' info:)" +repage -resize "$(( layer * 58 / 100 ))x$(( layer * 58 / 100 ))" \) \
    -gravity center -composite -strip "$dir/ic_launcher_foreground.png"
  echo "$dens: 位图 ${legacy}px / 图层 ${layer}px"
done

for f in ic_launcher ic_launcher_round; do
  cat > "$RES/mipmap-anydpi-v26/$f.xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@mipmap/ic_launcher_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
XML
done
rm -f "$RES/drawable/ic_launcher_foreground.xml"
echo "已写入 $RES"
