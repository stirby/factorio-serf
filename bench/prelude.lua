local s=game.surfaces.nauvis local f=game.forces.player
local st=f.get_item_production_statistics(s)
local function pm(n,cat) return st.get_flow_count{name=n,category=cat or 'input',
  precision_index=defines.flow_precision_index.one_minute,count=true} end
local function count(n) return s.count_entities_filtered{name=n,force='player'} end
local function machines(r) local out={} for _,e in pairs(s.find_entities_filtered{type={'assembling-machine','furnace'},force='player'}) do
  local ok,rr=pcall(e.get_recipe)
  local name=ok and rr and rr.name
  if not name and e.type=='furnace' then  -- idle furnaces only remember their last recipe
    local okp,pr=pcall(function() return e.previous_recipe end)
    name=okp and pr and (pr.name or (pr.name==nil and type(pr)=='table' and pr[1])) or nil
    if type(name)=='table' then name=name.name end
  end
  if name==r then out[#out+1]=e end end return out end
local function making(r) return #machines(r) end
local function finished(r) local k=0 for _,e in pairs(machines(r)) do k=k+e.products_finished end return k end
