#include "uvpack.h"
#include <vector>
#include <algorithm>
#include <numeric>
#include <cmath>
#include <random>
#include <chrono>
#include <limits>
#include <functional>

static const float INF = std::numeric_limits<float>::infinity();

// ════════════════════════════════════════════════════════════════════════════
//  Helpers
// ════════════════════════════════════════════════════════════════════════════

static void rotdims(float w, float h, float deg, float& rw, float& rh) {
    if (std::abs(deg) < 0.01f)                                        { rw=w; rh=h; return; }
    if (std::abs(deg-90.f)<0.01f || std::abs(deg-270.f)<0.01f)       { rw=h; rh=w; return; }
    float rad=deg*3.14159265f/180.f, ca=std::abs(std::cos(rad)), sa=std::abs(std::sin(rad));
    rw=w*ca+h*sa; rh=w*sa+h*ca;
}

// ════════════════════════════════════════════════════════════════════════════
//  Skyline
// ════════════════════════════════════════════════════════════════════════════

struct SkySeg { float x,y,w; };

struct Skyline {
    std::vector<SkySeg> sky;
    Skyline() { sky.push_back({0,0,1}); }

    bool insert(float rw, float rh, float& ox, float& oy) {
        float bY=INF, bX=0; int bI=-1;
        for (int i=0;i<(int)sky.size();i++) {
            if (sky[i].x+rw>1.f+1e-9f) continue;
            float mY=0,rem=rw; int j=i;
            while(rem>1e-9f&&j<(int)sky.size()){ mY=std::max(mY,sky[j].y); rem-=sky[j].w; j++; }
            if(rem>1e-9f) continue;
            if(mY<bY-1e-9f||(std::abs(mY-bY)<1e-9f&&sky[i].x<bX)){ bY=mY; bX=sky[i].x; bI=i; }
        }
        if(bI==-1){ bY=0; for(auto&s:sky) bY=std::max(bY,s.y); bX=0; }
        ox=bX; oy=bY;
        float top=bY+rh, pe=bX+rw;
        std::vector<SkySeg> ns; bool ins=false;
        for(auto&seg:sky){
            float se=seg.x+seg.w;
            if(se<=bX+1e-9f){ ns.push_back(seg); }
            else if(seg.x>=pe-1e-9f){ if(!ins){ns.push_back({bX,top,rw});ins=true;} ns.push_back(seg); }
            else{
                if(seg.x<bX-1e-9f) ns.push_back({seg.x,seg.y,bX-seg.x});
                if(!ins){ns.push_back({bX,top,rw});ins=true;}
                if(se>pe+1e-9f) ns.push_back({pe,seg.y,se-pe});
            }
        }
        if(!ins) ns.push_back({bX,top,rw});
        sky.clear();
        for(auto&s:ns){
            if(!sky.empty()&&std::abs(sky.back().y-s.y)<1e-9f&&std::abs(sky.back().x+sky.back().w-s.x)<1e-9f)
                sky.back().w+=s.w;
            else sky.push_back(s);
        }
        return true;
    }
    float height() const { float h=0; for(auto&s:sky) h=std::max(h,s.y); return h; }
};

// ════════════════════════════════════════════════════════════════════════════
//  MaxRects
// ════════════════════════════════════════════════════════════════════════════

struct Rect { float x,y,w,h; };

struct MaxRects {
    std::vector<Rect> fr, ur;
    MaxRects() { fr.push_back({0,0,1,100}); }

    std::pair<float,float> sc(const Rect&f,float rw,float rh,int heur) const {
        float lw=f.w-rw, lh=f.h-rh;
        switch(heur){
            case UV_BSSF: return {std::min(lw,lh),std::max(lw,lh)};
            case UV_BLSF: return {std::max(lw,lh),std::min(lw,lh)};
            case UV_BAF:  return {lw*lh,std::min(lw,lh)};
            case UV_BL:   return {f.y,f.x};
            case UV_CP: {
                float cp=0;
                if(f.x<1e-9f) cp+=rh; if(f.y<1e-9f) cp+=rw;
                if(std::abs(f.x+rw-1)<1e-9f) cp+=rh;
                for(auto&u:ur){
                    if(std::abs(f.x-(u.x+u.w))<1e-9f||std::abs(f.x+rw-u.x)<1e-9f){
                        float ov=std::min(f.y+rh,u.y+u.h)-std::max(f.y,u.y); if(ov>0)cp+=ov; }
                    if(std::abs(f.y-(u.y+u.h))<1e-9f||std::abs(f.y+rh-u.y)<1e-9f){
                        float ov=std::min(f.x+rw,u.x+u.w)-std::max(f.x,u.x); if(ov>0)cp+=ov; }
                }
                return {-cp,std::min(lw,lh)};
            }
            default: return {std::min(lw,lh),std::max(lw,lh)};
        }
    }

    void split(const Rect&p){
        std::vector<Rect> res; res.reserve(fr.size()*2);
        for(auto&f:fr){
            if(p.x>=f.x+f.w-1e-9f||p.x+p.w<=f.x+1e-9f||p.y>=f.y+f.h-1e-9f||p.y+p.h<=f.y+1e-9f){
                res.push_back(f); continue; }
            if(p.x>f.x+1e-9f)           res.push_back({f.x,f.y,p.x-f.x,f.h});
            if(p.x+p.w<f.x+f.w-1e-9f)  res.push_back({p.x+p.w,f.y,f.x+f.w-p.x-p.w,f.h});
            if(p.y>f.y+1e-9f)           res.push_back({f.x,f.y,f.w,p.y-f.y});
            if(p.y+p.h<f.y+f.h-1e-9f)  res.push_back({f.x,p.y+p.h,f.w,f.y+f.h-p.y-p.h});
        }
        fr=std::move(res);
    }

    void prune(){
        int n=(int)fr.size(); std::vector<bool> skip(n,false);
        for(int i=0;i<n;i++){
            if(skip[i]) continue;
            for(int j=0;j<n;j++){
                if(i==j||skip[j]) continue;
                auto&a=fr[i]; auto&b=fr[j];
                if(a.x>=b.x-1e-9f&&a.y>=b.y-1e-9f&&a.x+a.w<=b.x+b.w+1e-9f&&a.y+a.h<=b.y+b.h+1e-9f)
                    { skip[i]=true; break; }
            }
        }
        std::vector<Rect> res; res.reserve(n);
        for(int i=0;i<n;i++) if(!skip[i]) res.push_back(fr[i]);
        fr=std::move(res);
    }

    bool insert(float rw, float rh, int heur, float& ox, float& oy){
        int bi=-1; std::pair<float,float> bs={INF,INF};
        for(int i=0;i<(int)fr.size();i++){
            auto&f=fr[i];
            if(rw<=f.w+1e-9f&&rh<=f.h+1e-9f){ auto s=sc(f,rw,rh,heur); if(s<bs){bs=s;bi=i;} }
        }
        if(bi==-1) return false;
        Rect pl={fr[bi].x,fr[bi].y,rw,rh};
        ox=pl.x; oy=pl.y;
        ur.push_back(pl); split(pl); prune();
        return true;
    }
    float height() const { float h=0; for(auto&u:ur) h=std::max(h,u.y+u.h); return h; }
};

// ════════════════════════════════════════════════════════════════════════════
//  Attempt
// ════════════════════════════════════════════════════════════════════════════

struct Island  { float w,h,area; };
struct Place   { float x,y,angle; };

static float attempt(const std::vector<Island>& data,
                     const std::vector<int>& order,
                     const std::vector<float>& rots,
                     float margin, int method, int heur,
                     std::vector<Place>& out)
{
    int n=(int)data.size(); out.resize(n);
    Skyline sky; MaxRects mr;
    for(int idx:order){
        float rw,rh; rotdims(data[idx].w,data[idx].h,rots[idx],rw,rh);
        float pw=rw+margin*2, ph=rh+margin*2, px=0,py=0;
        if(method==UV_SKYLINE) {
            sky.insert(pw,ph,px,py);
        } else if(!mr.insert(pw,ph,heur,px,py)) {
            return -1.f;
        }
        out[idx]={px+margin,py+margin,rots[idx]};
    }
    float th=(method==UV_SKYLINE)?sky.height():mr.height();
    if(th<1e-9f) return 0;
    float tot=0; for(auto&d:data) tot+=d.area;
    return tot/(1.f*th);
}

static std::vector<float> get_angles(int step){
    if(step<=0) return {0};
    std::vector<float> a;
    for(int d=0;d<360;d+=step) a.push_back((float)d);
    return a;
}

// ════════════════════════════════════════════════════════════════════════════
//  Iterative optimizer
// ════════════════════════════════════════════════════════════════════════════

static float iter_opt(const std::vector<Island>& data, const UVPackConfig& cfg,
                      float min_occ, std::vector<Place>& best_pl)
{
    int n=(int)data.size();
    auto angles=get_angles(cfg.rotation_step);
    float best=min_occ, tlim=cfg.time_limit>0.01f?cfg.time_limit:999999.f;
    int   iters=0;
    auto  t0=std::chrono::steady_clock::now();
    auto  elapsed=[&](){ return std::chrono::duration<float>(std::chrono::steady_clock::now()-t0).count(); };
    auto  done=[&](){ return iters>=cfg.max_iter||elapsed()>=tlim||best>=0.98f; };

    std::vector<Place> pl; std::vector<int> ord(n); std::vector<float> rots(n,0);

    auto try_it=[&](const std::vector<int>&o, const std::vector<float>&r){
        if(done()) return;
        float occ=attempt(data,o,r,cfg.margin,cfg.method,cfg.heuristic,pl);
        iters++;
        if(occ>best+1e-6f){ best=occ; best_pl=pl; }
    };

    using SF=std::function<bool(int,int)>;
    std::vector<SF> sorts={
        [&](int a,int b){ return data[a].area>data[b].area; },
        [&](int a,int b){ return std::max(data[a].w,data[a].h)>std::max(data[b].w,data[b].h); },
        [&](int a,int b){ return data[a].h>data[b].h; },
        [&](int a,int b){ return data[a].w>data[b].w; },
        [&](int a,int b){ return (data[a].w+data[a].h)>(data[b].w+data[b].h); },
    };

    for(auto&sf:sorts){
        if(done()) break;
        std::iota(ord.begin(),ord.end(),0);
        std::sort(ord.begin(),ord.end(),sf);
        try_it(ord,std::vector<float>(n,0));
        if(angles.size()>1){
            for(float a:angles){ if(done()||a==0) continue; try_it(ord,std::vector<float>(n,a)); }
            // smart: per-island rotation that minimises max(rw,rh)
            std::vector<float> smart(n);
            for(int i=0;i<n;i++){
                float bm=INF,ba=0;
                for(float a:angles){ float rw,rh; rotdims(data[i].w,data[i].h,a,rw,rh); float m=std::max(rw,rh); if(m<bm){bm=m;ba=a;} }
                smart[i]=ba;
            }
            try_it(ord,smart);
            std::vector<float> port(n);
            for(int i=0;i<n;i++) port[i]=(data[i].h>data[i].w)?0:90;
            try_it(ord,port);
        }
    }

    std::mt19937 rng(12345);
    std::uniform_real_distribution<float> ud(0,1);
    std::uniform_int_distribution<int>    ai(0,(int)angles.size()-1);
    while(!done()){
        std::iota(ord.begin(),ord.end(),0);
        if(ud(rng)<0.7f){
            std::uniform_real_distribution<float> jitter(0.8f,1.2f);
            std::sort(ord.begin(),ord.end(),[&](int a,int b){ return data[a].area*jitter(rng)>data[b].area*jitter(rng); });
        } else { std::shuffle(ord.begin(),ord.end(),rng); }
        for(auto&r:rots) r=angles[ai(rng)];
        try_it(ord,rots);
    }
    return best;
}

// ════════════════════════════════════════════════════════════════════════════
//  Simulated Annealing
// ════════════════════════════════════════════════════════════════════════════

static float sa_opt(const std::vector<Island>& data, const UVPackConfig& cfg,
                    float min_occ, std::vector<Place>& best_pl)
{
    int n=(int)data.size();
    auto angles=get_angles(cfg.rotation_step);
    float tlim=cfg.time_limit>0.01f?cfg.time_limit:999999.f;
    auto  t0=std::chrono::steady_clock::now();
    auto  elapsed=[&](){ return std::chrono::duration<float>(std::chrono::steady_clock::now()-t0).count(); };

    std::mt19937 rng(42);
    std::uniform_real_distribution<float> ud(0,1);
    std::uniform_int_distribution<int>    ai(0,(int)angles.size()-1);
    std::uniform_int_distribution<int>    ri(0,n-1);

    std::vector<int>   ord(n); std::iota(ord.begin(),ord.end(),0);
    std::sort(ord.begin(),ord.end(),[&](int a,int b){ return data[a].area>data[b].area; });
    std::vector<float> rots(n,0);

    std::vector<Place> pl;
    float cur=attempt(data,ord,rots,cfg.margin,cfg.method,cfg.heuristic,pl);
    float best=min_occ;
    if(cur>best+1e-6f){ best=cur; best_pl=pl; }
    else if(cur < 0.f){ cur=min_occ; }

    float temp=cfg.sa_initial_temp; int it=0;
    while(it<cfg.max_iter&&elapsed()<tlim&&best<0.98f){
        auto no=ord; auto nr=rots;
        float act=ud(rng);
        if(n<2||act<0.25f){ nr[ri(rng)]=angles[ai(rng)]; }
        else if(act<0.50f){ int i=ri(rng),j=ri(rng); std::swap(no[i],no[j]); }
        else if(act<0.75f){ int i=ri(rng),j=ri(rng); auto x=no[i]; no.erase(no.begin()+i); no.insert(no.begin()+j,x); }
        else{ int i=ri(rng),j=ri(rng); if(i>j)std::swap(i,j); std::reverse(no.begin()+i,no.begin()+j+1); }

        float nw=attempt(data,no,nr,cfg.margin,cfg.method,cfg.heuristic,pl);
        if(nw < 0.f){ temp*=cfg.sa_cooling_rate; it++; continue; }
        float d=nw-cur; bool acc=d>0;
        if(!acc&&temp>1e-12f){ float p=std::exp(d/temp); acc=ud(rng)<p; }
        if(acc){ ord=no; rots=nr; cur=nw; }
        if(cur>best+1e-6f){ best=cur; best_pl=pl; }
        temp*=cfg.sa_cooling_rate; it++;
    }
    return best;
}

// ════════════════════════════════════════════════════════════════════════════
//  Public API
// ════════════════════════════════════════════════════════════════════════════

UVPACK_API float uvpack_run(const UVIsland* islands, int n_islands,
                            const UVPackConfig* cfg, UVPlacement* out)
{
    if(!islands||n_islands<=0||!cfg||!out) return 0;

    std::vector<Island> data(n_islands);
    for(int i=0;i<n_islands;i++) data[i]={islands[i].w,islands[i].h,islands[i].area};

    std::vector<Place> best_pl(n_islands,{0,0,0});
    float best=0;

    if(cfg->optimizer==UV_OPT_NONE){
        std::vector<int> ord(n_islands); std::iota(ord.begin(),ord.end(),0);
        std::sort(ord.begin(),ord.end(),[&](int a,int b){ return data[a].area>data[b].area; });
        std::vector<float> rots(n_islands,0);
        best=attempt(data,ord,rots,cfg->margin,cfg->method,cfg->heuristic,best_pl);
        if(best < 0.f) best = cfg->min_occupancy;
    } else if(cfg->optimizer==UV_OPT_ITERATIVE){
        best=iter_opt(data,*cfg,cfg->min_occupancy,best_pl);
    } else {
        best=sa_opt(data,*cfg,cfg->min_occupancy,best_pl);
    }

    for(int i=0;i<n_islands;i++)
        out[i]={islands[i].id, best_pl[i].x, best_pl[i].y, best_pl[i].angle};

    return best;
}

UVPACK_API const char* uvpack_version(void) { return "uvpack 1.0.0"; }
