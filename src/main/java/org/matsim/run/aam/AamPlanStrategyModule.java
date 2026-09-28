package org.matsim.run.aam;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.api.core.v01.replanning.PlanStrategyModule;
import org.matsim.core.replanning.ReplanningContext;
import org.matsim.core.router.*;
import org.matsim.core.router.TripStructureUtils.Trip;

/** Preserve parked private vehicles: car/bike AAM alternatives are paired home-return tours. */
public final class AamPlanStrategyModule implements PlanStrategyModule {
    private final Scenario scenario;private final Random random;private final List<AamMultimodalRoutingModule.Vertiport> ports;
    public AamPlanStrategyModule(Scenario s,List<AamMultimodalRoutingModule.Vertiport> v,long seed){scenario=s;ports=v;random=new Random(seed);}
    public void prepareReplanning(ReplanningContext c){}
    public void handlePlan(Plan p){
        List<Trip> ts=new ArrayList<>(TripStructureUtils.getTrips(p));if(ts.isEmpty())return;
        AamMainModeIdentifier id=new AamMainModeIdentifier();
        for(Trip t:ts)if(id.identifyMainMode(t.getTripElements()).equals("aam"))return;
        Set<String> chains=new HashSet<>();
        for(Trip t:ts)for(Leg l:t.getLegsOnly())if(List.of("car","bike").contains(l.getMode()))chains.add(l.getMode());
        if(!chains.isEmpty()){
            // No teleportation of a private car/bike across the flight. It stays at the home-side vertiport.
            if(chains.size()!=1 || ts.size()!=2)return;
            String m=chains.iterator().next();
            if(!org.matsim.core.config.ConfigUtils.addOrGetModule(scenario.getConfig(),AamConfigGroup.class).modes().contains(m))return;
            if(!id.identifyMainMode(ts.get(0).getTripElements()).equals(m) || !id.identifyMainMode(ts.get(1).getTripElements()).equals(m))return;
            Coord a=coord(ts.get(0).getOriginActivity()),b=coord(ts.get(1).getDestinationActivity());
            if(a==null||b==null||AamMultimodalRoutingModule.distance(a,b)>5 || !ts.get(0).getOriginActivity().getType().startsWith("home"))return;
            if(!eligible(ts.get(0))||!eligible(ts.get(1)))return;
            p.getAttributes().putAttribute("aam_park_mode",m);
            for(Trip t:ts)insert(p,t);
        } else {
            List<Trip> eligible=new ArrayList<>();for(Trip t:ts)if(eligible(t))eligible.add(t);
            if(!eligible.isEmpty())insert(p,eligible.get(random.nextInt(eligible.size())));
        }
    }
    private boolean eligible(Trip t){return AamMultimodalRoutingModule.isEligible(ports,coord(t.getOriginActivity()),coord(t.getDestinationActivity()));}
    private Coord coord(Activity a){if(a.getCoord()!=null)return a.getCoord();return a.getLinkId()==null?null:scenario.getNetwork().getLinks().get(a.getLinkId()).getCoord();}
    private void insert(Plan p,Trip t){Leg l=scenario.getPopulation().getFactory().createLeg("aam");
        l.setDepartureTime(TripStructureUtils.getDepartureTime(t).seconds());TripStructureUtils.setRoutingMode(l,"aam");
        TripRouter.insertTrip(p,t.getOriginActivity(),Collections.singletonList(l),t.getDestinationActivity());}
    public void finishReplanning(){}
}
