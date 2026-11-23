#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <queue>
#include <random>
#include <regex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

// A deliberately dependency-free JSON CLI. The API supplies a stable schema;
// keeping this binary standalone makes it simple to unit test and benchmark.
struct Room { int id{}; std::string name; double area{}, minW{}, minH{}, x{}, y{}, w{}, h{}; };
struct Plot { double w{}, h{}; };
struct Candidate { std::vector<Room> rooms; double cost{}, efficiency{}, adjacency{}, circulation{}; bool feasible{}; };
template <typename T> T clamp_value(T value, T low, T high) { return std::max(low, std::min(value, high)); }

bool intersects(const Room& a, const Room& b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}
bool inside(const Room& r, const Plot& p) { return r.x >= 0 && r.y >= 0 && r.x + r.w <= p.w && r.y + r.h <= p.h; }
double distance(const Room& a, const Room& b) {
  double dx = std::max({a.x - (b.x + b.w), b.x - (a.x + a.w), 0.0});
  double dy = std::max({a.y - (b.y + b.h), b.y - (a.y + a.h), 0.0});
  return std::hypot(dx, dy);
}

// Dijkstra on a complete weighted room graph; it provides true route/connectivity data
// while the visual layer draws centroid paths.
double dijkstra(const std::vector<Room>& rooms) {
  if (rooms.size() < 2) return 0;
  const int n = static_cast<int>(rooms.size());
  std::vector<double> d(n, std::numeric_limits<double>::infinity()); d[0] = 0;
  using Item = std::pair<double,int>; std::priority_queue<Item, std::vector<Item>, std::greater<>> q; q.push({0,0});
  while (!q.empty()) { Item current = q.top(); q.pop(); double cost = current.first; int u = current.second; if (cost != d[u]) continue;
    for (int v=0; v<n; ++v) if (u != v) { double nd = cost + distance(rooms[u], rooms[v]); if (nd < d[v]) { d[v]=nd; q.push({nd,v}); } }
  }
  double sum=0; for (double v : d) sum += v; return sum / std::max(1, n-1);
}

Candidate evaluate(Candidate c, const Plot& plot) {
  double penalty = 0, used = 0, adjacent = 0;
  for (size_t i=0;i<c.rooms.size();++i) {
    const auto& r = c.rooms[i]; used += r.w*r.h;
    if (!inside(r, plot) || r.w < r.minW || r.h < r.minH || r.w*r.h + 0.001 < r.area) penalty += 10000;
    for (size_t j=i+1;j<c.rooms.size();++j) { if (intersects(r,c.rooms[j])) penalty += 10000; else if (distance(r,c.rooms[j]) < 1.5) adjacent += 1; }
  }
  c.efficiency = std::min(100.0, 100.0*used/(plot.w*plot.h));
  c.adjacency = c.rooms.size() < 2 ? 100 : std::min(100.0, 100.0*adjacent/(c.rooms.size()-1));
  double route = dijkstra(c.rooms); c.circulation = std::max(0.0, 100.0 - route*5.0);
  c.cost = penalty + (100-c.adjacency)*2 + (100-c.circulation) + (100-c.efficiency)*.4;
  c.feasible = penalty == 0; return c;
}

Candidate pack(const std::vector<Room>& specs, const Plot& plot, int variant) {
  Candidate c; double cursorX=0, cursorY=0, rowH=0; const double gap=.35;
  std::vector<Room> ordered=specs;
  if (variant % 2) std::reverse(ordered.begin(), ordered.end());
  for (auto r : ordered) {
    r.w = std::max(r.minW, std::sqrt(r.area) * (variant % 3 == 0 ? 1.15 : .9));
    r.h = std::max(r.minH, std::ceil(r.area/r.w*10)/10.0);
    if (cursorX+r.w > plot.w) { cursorX=0; cursorY += rowH+gap; rowH=0; }
    r.x=cursorX; r.y=cursorY; cursorX += r.w+gap; rowH=std::max(rowH,r.h); c.rooms.push_back(r);
  }
  return evaluate(c,plot);
}

Candidate anneal(Candidate c, const Plot& p, std::mt19937& rng) {
  c=evaluate(c,p); Candidate best=c; std::uniform_real_distribution<double> shift(-.8,.8), coin(0,1); double temp=25;
  for (int k=0;k<180;++k) { Candidate next=c; if (!next.rooms.empty()) { Room& r=next.rooms[rng()%next.rooms.size()]; r.x=clamp_value(r.x+shift(rng),0.0,std::max(0.0,p.w-r.w)); r.y=clamp_value(r.y+shift(rng),0.0,std::max(0.0,p.h-r.h)); }
    next=evaluate(next,p); if (next.cost<c.cost || coin(rng)<std::exp((c.cost-next.cost)/temp)) c=next; if(c.cost<best.cost) best=c; temp*=.975; }
  return best;
}

std::string escape(std::string s) { std::string out; for(char ch:s) { if(ch=='"'||ch=='\\') out+='\\'; out+=ch; } return out; }
double number(const std::string& s, const std::string& key, double fallback=0) { std::smatch m; std::regex r("\\\""+key+"\\\"\\s*:\\s*([-0-9.]+)"); return std::regex_search(s,m,r) ? std::stod(m[1]) : fallback; }
std::string text(const std::string& s, const std::string& key, std::string fallback="") { std::smatch m; std::regex r("\\\""+key+"\\\"\\s*:\\s*\\\"([^\\\"]*)\\\""); return std::regex_search(s,m,r) ? m[1].str() : fallback; }

int main() {
  std::string input((std::istreambuf_iterator<char>(std::cin)), {}); Plot plot{number(input,"width"),number(input,"height")};
  if (plot.w<=0 || plot.h<=0) { std::cout << "{\"error\":\"Plot dimensions must be positive\"}"; return 1; }
  std::vector<Room> rooms; std::regex object("\\{[^{}]*\\\"required_area\\\"[^{}]*\\}");
  for (auto it=std::sregex_iterator(input.begin(),input.end(),object); it!=std::sregex_iterator(); ++it) { std::string o=it->str(); Room r; r.id=(int)number(o,"id"); r.name=text(o,"name","Room"); r.area=number(o,"required_area"); r.minW=number(o,"min_width",2); r.minH=number(o,"min_height",2); if(r.area>0) rooms.push_back(r); }
  if(rooms.empty()) { std::cout << "{\"error\":\"At least one room is required\"}"; return 1; }
  int count=clamp_value((int)number(input,"candidate_count",3),1,5); int seed=(int)number(input,"seed",42); std::vector<Candidate> results(count);
  // Independent candidates are truly evaluated in parallel while retaining deterministic seeds.
#ifdef ARCHOPT_SINGLE_THREAD
  // Kept solely for obsolete MinGW distributions compiled without libstdc++ threading.
  for(int i=0;i<count;++i) { std::mt19937 rng(seed+i); results[i] = anneal(pack(rooms,plot,i),plot,rng); }
#else
  std::vector<std::thread> workers;
  for(int i=0;i<count;++i) workers.push_back(std::thread([&,i]{ std::mt19937 rng(seed+i); results[i] = anneal(pack(rooms,plot,i),plot,rng); }));
  for(size_t i=0;i<workers.size();++i) workers[i].join();
#endif
  std::sort(results.begin(),results.end(),[](const Candidate& a,const Candidate& b){return a.cost<b.cost;});
  std::cout << "{\"evaluated\":"<<count<<",\"layouts\":[";
  for(size_t i=0;i<results.size();++i) { if(i) std::cout<<','; const auto& c=results[i]; std::cout<<"{\"cost\":"<<c.cost<<",\"feasible\":"<<(c.feasible?"true":"false")<<",\"efficiency\":"<<c.efficiency<<",\"adjacency\":"<<c.adjacency<<",\"circulation\":"<<c.circulation<<",\"rooms\":[";
    for(size_t j=0;j<c.rooms.size();++j) { if(j)std::cout<<','; const auto&r=c.rooms[j]; std::cout<<"{\"id\":"<<r.id<<",\"name\":\""<<escape(r.name)<<"\",\"x\":"<<r.x<<",\"y\":"<<r.y<<",\"width\":"<<r.w<<",\"height\":"<<r.h<<"}"; } std::cout<<"]}"; }
  std::cout<<"]}";
}
