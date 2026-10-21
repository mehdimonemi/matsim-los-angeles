package org.matsim.run.aam;
import java.util.*;
import javax.inject.Provider;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.api.core.v01.replanning.PlanStrategyModule;
import org.matsim.core.replanning.ReplanningContext;
import org.matsim.core.router.*;
import org.matsim.core.router.TripStructureUtils.Trip;
import org.matsim.facilities.FacilitiesUtils;

/** Screen every trip, rank intent, expose only fully routed choices. */
public final class AamPlanStrategyModule implements PlanStrategyModule {
    public static final String AAM_PLAN_TYPE="aam";
    private final Scenario scenario;private final List<AamMultimodalRoutingModule.Vertiport> ports;
    private final Provider<RoutingModule> aamRouters;
    private final Provider<TripRouter> groundRouters;
    public AamPlanStrategyModule(Scenario s,List<AamMultimodalRoutingModule.Vertiport> v,long seed){this(s,v,seed,null,null);}
    public AamPlanStrategyModule(Scenario s,List<AamMultimodalRoutingModule.Vertiport> v,long seed,Provider<RoutingModule> routers){this(s,v,seed,routers,null);}
    public AamPlanStrategyModule(Scenario s,List<AamMultimodalRoutingModule.Vertiport> v,long seed,Provider<RoutingModule> routers,Provider<TripRouter> ground){scenario=s;ports=v;aamRouters=routers;groundRouters=ground;}
    public void prepareReplanning(ReplanningContext c){}
    public void handlePlan(Plan p){addAlternative(p,false);}
    boolean addAlternative(Plan p,boolean ignored){return addAlternative(p,Set.of(),false);}
    boolean addAlternative(Plan p,Set<Integer> excluded){return addAlternative(p,excluded,false);}
    boolean addAlternative(Plan p,Set<Integer> excluded,boolean stopAfterFirstFeasibleTrip){
        AamCandidateScreen screen=AamCandidateScreen.get(scenario);
        List<AamCandidateScreen.Candidate> screened=screen.screen(p,ports);
        if(AamFeederPolicy.hasGenuineAam(p)||aamRouters==null)return false;
        List<Trip> trips=new ArrayList<>(TripStructureUtils.getTrips(p));
        AamConfigGroup cfg=org.matsim.core.config.ConfigUtils.addOrGetModule(scenario.getConfig(),AamConfigGroup.class);
        List<Choice> choices=new ArrayList<>();
        AamMainModeIdentifier modes=new AamMainModeIdentifier();
        for(int i=0;i<trips.size();i++){
            AamCandidateScreen.Candidate c=screened.get(i);if(!c.temporal||excluded.contains(i))continue;
            String mode=modes.identifyMainMode(trips.get(i).getTripElements());
            if(!List.of("car","bike").contains(mode))choices.add(new Choice(i,i,null,c.proxy-tripCost(trips.get(i),p.getPerson()),null));
            else if(trips.get(i).getOriginActivity().getType().startsWith("home")&&cfg.modes().contains(mode)){
                for(int j=i+1;j<trips.size();j++)if(trips.get(j).getDestinationActivity().getType().startsWith("home")){
                    Coord home=trips.get(i).getOriginActivity().getCoord(),back=trips.get(j).getDestinationActivity().getCoord();
                    boolean chain=home!=null&&back!=null&&AamMultimodalRoutingModule.distance(home,back)<5
                        &&screened.get(j).temporal&&mode.equals(modes.identifyMainMode(trips.get(j).getTripElements()));
                    for(int k=i;k<=j;k++)for(Leg l:trips.get(k).getLegsOnly())if(List.of("car","bike").contains(l.getMode())&&!mode.equals(l.getMode()))chain=false;
                    if(chain&&!excluded.contains(j)){
                        // Bound home-side parking choices by the same nearest-port shortlist
                        // used by feeder routing. Both directions use this SAME site.
                        for(AamMultimodalRoutingModule.Vertiport port:parkingCandidates(home,cfg))
                                choices.add(new Choice(i,j,mode,c.proxy+screened.get(j).proxy-tripCost(trips.get(i),p.getPerson())-tripCost(trips.get(j),p.getPerson()),port.id));
                    }
                    else screen.outcome(c,"private_return_chain",p.getPerson());
                    break;
                }
            }else screen.outcome(c,"private_return_chain",p.getPerson());
        }
        if(cfg.getAllowCarAtHomeAlternatives())for(int i=0;i<trips.size();i++){
            if(!trips.get(i).getOriginActivity().getType().startsWith("home")||!"car".equals(modes.identifyMainMode(trips.get(i).getTripElements())))continue;
            for(int j=i+1;j<trips.size();j++)if(trips.get(j).getDestinationActivity().getType().startsWith("home")){
                Coord home=trips.get(i).getOriginActivity().getCoord(),back=trips.get(j).getDestinationActivity().getCoord();
                boolean closed=home!=null&&back!=null&&AamMultimodalRoutingModule.distance(home,back)<5;
                for(int k=i;k<=j;k++)if(trips.get(k).getLegsOnly().stream().anyMatch(l->"bike".equals(l.getMode())))closed=false;
                if(closed)for(int k=i;k<=j;k++)if(screened.get(k).temporal&&!excluded.contains(k)){
                    Choice choice=new Choice(k,k,null,screened.get(k).proxy-tripCost(trips.get(k),p.getPerson()),null);
                    choice.homeFirst=i;choice.homeLast=j;choices.add(choice);
                }
                break;
            }
        }
        choices.sort(Comparator.comparingDouble((Choice c)->c.cost).thenComparingInt(c->c.first).thenComparing(c->c.parking==null?"":c.parking));
        List<PlanElement> original=new ArrayList<>(p.getPlanElements());
        Map<String,Object> attributes=new HashMap<>(p.getAttributes().getAsMap());
        int attempts=0;double bestCost=Double.POSITIVE_INFINITY;
        double originalCost=planCost(p);List<PlanElement> bestElements=null;Map<String,Object> bestAttributes=null;
        Set<String> attemptedTrips=new HashSet<>();String selectedFeasibleTripKey=null;
        for(Choice choice:choices){
            String key=choice.first+":"+choice.last;
            // At startup, each protected alternative is a separate plan and
            // will use a different excluded trip. Once this trip has a feasible
            // route, finish its same-trip parking variants, then avoid routing
            // additional trip candidates solely to choose one plan to protect.
            if(stopAfterFirstFeasibleTrip&&selectedFeasibleTripKey!=null&&!selectedFeasibleTripKey.equals(key))continue;
            if(!attemptedTrips.contains(key)&&attempts>=cfg.getMaximumRoutedCandidates())continue;
            if(attemptedTrips.add(key))attempts++;
            List<GroundTripRef> convertedGroundTrips=new ArrayList<>();
            restore(p,original,attributes);
            if(choice.homeFirst>=0){
                // Car never leaves home; every private-car movement in this tour
                // is replaced, while later independent home tours remain intact.
                for(int k=choice.homeFirst;k<=choice.homeLast;k++)if(trips.get(k).getLegsOnly().stream().anyMatch(l->"car".equals(l.getMode()))){
                    Leg ride=scenario.getPopulation().getFactory().createLeg("ride");TripStructureUtils.setRoutingMode(ride,"ride");
                    TripRouter.insertTrip(p,trips.get(k).getOriginActivity(),List.of(ride),trips.get(k).getDestinationActivity());
                    if(k!=choice.first)convertedGroundTrips.add(new GroundTripRef(trips.get(k).getOriginActivity(),trips.get(k).getDestinationActivity()));
                }
            }
            if(choice.privateMode!=null){
                p.getAttributes().putAttribute("aam_park_mode",choice.privateMode);
                p.getAttributes().putAttribute("aam_park_vertiport",choice.parking);
                Coord home=trips.get(choice.first).getOriginActivity().getCoord();
                p.getAttributes().putAttribute("aam_park_home_x",home.getX());p.getAttributes().putAttribute("aam_park_home_y",home.getY());
                // The private vehicle stays parked; intermediate movements use ride.
                for(int k=choice.first+1;k<choice.last;k++)if(trips.get(k).getLegsOnly().stream().anyMatch(l->List.of("car","bike").contains(l.getMode()))){
                    Leg ride=scenario.getPopulation().getFactory().createLeg("ride");TripStructureUtils.setRoutingMode(ride,"ride");
                    TripRouter.insertTrip(p,trips.get(k).getOriginActivity(),List.of(ride),trips.get(k).getDestinationActivity());
                    convertedGroundTrips.add(new GroundTripRef(trips.get(k).getOriginActivity(),trips.get(k).getDestinationActivity()));
                }
            }
            long start=System.nanoTime();screen.routeAttempts.incrementAndGet();
            boolean success=route(p,trips.get(choice.first),screened.get(choice.first));
            if(success&&choice.last!=choice.first)success=route(p,trips.get(choice.last),screened.get(choice.last));
            screen.routingNanos.addAndGet(System.nanoTime()-start);
            if(success&&groundRouters!=null)for(GroundTripRef changed:convertedGroundTrips)
                AamFeederPolicy.routeConvertedGroundTrip(scenario,p,changed.origin,changed.destination,groundRouters.get(),"aam_candidate");
            if(success&&AamFeederPolicy.hasGenuineAam(p)){
                p.getAttributes().putAttribute("aam_alternative_kind",choice.homeFirst>=0?"car_at_home_tour":choice.privateMode==null?"single_trip":"paired_tour");
                p.getAttributes().putAttribute("aam_candidate_indices",choice.first+","+choice.last);
                screen.outcome(screened.get(choice.first),"routed",p.getPerson());screen.outcome(screened.get(choice.last),"routed",p.getPerson());
                double cost=planCost(p);
                if(cost<bestCost){bestCost=cost;bestElements=new ArrayList<>(p.getPlanElements());bestAttributes=new HashMap<>(p.getAttributes().getAsMap());}
                if(stopAfterFirstFeasibleTrip&&selectedFeasibleTripKey==null)selectedFeasibleTripKey=key;
                continue;
            }
            screen.outcome(screened.get(choice.first),choice.privateMode==null?"network_or_service_infeasible":"private_return_chain",p.getPerson());
            if(choice.last!=choice.first)screen.outcome(screened.get(choice.last),"private_return_chain",p.getPerson());
        }
        if(bestElements!=null){
            restore(p,bestElements,bestAttributes);p.setType(AAM_PLAN_TYPE);p.setScore(null);
            p.getAttributes().putAttribute("aam_predicted_generalized_gain",originalCost-bestCost);return true;
        }
        restore(p,original,attributes);return false;
    }
    List<AamMultimodalRoutingModule.Vertiport> parkingCandidates(Coord home,AamConfigGroup cfg){
        double radius=Math.min(cfg.getMaxAccessDistanceMiles(),cfg.getMaxEgressDistanceMiles())*RunDynamicAamLosAngelesScenario.MILE;
        List<AamMultimodalRoutingModule.Vertiport> eligible=new ArrayList<>();
        for(AamMultimodalRoutingModule.Vertiport port:ports)
            if(home!=null&&AamMultimodalRoutingModule.distance(home,port.coord)<=radius)eligible.add(port);
        eligible.sort(Comparator.comparingDouble((AamMultimodalRoutingModule.Vertiport port)->AamMultimodalRoutingModule.distance(home,port.coord)).thenComparing(port->port.id));
        return eligible.subList(0,Math.min(cfg.getCandidateVertiports(),eligible.size()));
    }
    // Route-based generalized travel cost, not an experienced MATSim score.
    // Activity opening/closing and parking events remain authoritative in QSim.
    double tripCost(Trip trip,Person person){
        double cost=0;
        for(Leg leg:trip.getLegsOnly()){
            double distance=leg.getRoute()==null?AamMultimodalRoutingModule.distance(trip.getOriginActivity().getCoord(),trip.getDestinationActivity().getCoord())*1.4:leg.getRoute().getDistance();
            if(!Double.isFinite(distance))distance=0;
            double speed="walk".equals(leg.getMode())?1.0555556:"bike".equals(leg.getMode())?3.1388889:13.89;
            double time=leg.getTravelTime().orElse(leg.getRoute()==null?distance/speed:leg.getRoute().getTravelTime().orElse(distance/speed));
            org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ModeParams mp=scenario.getConfig().planCalcScore().getModes().get(leg.getMode());
            if(mp==null)continue;
            cost+=(scenario.getConfig().planCalcScore().getPerforming_utils_hr()-mp.getMarginalUtilityOfTraveling())*time/3600-mp.getConstant()
                -mp.getMonetaryDistanceRate()*distance*AamMultimodalRoutingModule.moneyUtility(person)-mp.getMarginalUtilityOfDistance()*distance;
            if("aam_drt".equals(leg.getMode())){
                AamConfigGroup cfg=org.matsim.core.config.ConfigUtils.addOrGetModule(scenario.getConfig(),AamConfigGroup.class);
                cost+=(cfg.getBaseFare()+cfg.getFarePerMile()*distance/RunDynamicAamLosAngelesScenario.MILE)*AamMultimodalRoutingModule.moneyUtility(person);
            }
        }return cost;
    }
    private double planCost(Plan plan){
        double cost=0;Set<String> modes=new HashSet<>();
        for(Trip trip:TripStructureUtils.getTrips(plan))cost+=tripCost(trip,plan.getPerson());
        for(Leg leg:TripStructureUtils.getLegs(plan))if(modes.add(leg.getMode())){
            org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ModeParams mp=scenario.getConfig().planCalcScore().getModes().get(leg.getMode());
            if(mp!=null)cost-=mp.getDailyUtilityConstant()+mp.getDailyMonetaryConstant()*AamMultimodalRoutingModule.moneyUtility(plan.getPerson());
        }return cost;
    }
    private boolean route(Plan plan,Trip trip,AamCandidateScreen.Candidate candidate){
        Person person=plan.getPerson();if(person==null)return false;
        Plan selected=person.getSelectedPlan();person.setSelectedPlan(plan);
        try{
            List<? extends PlanElement> route=aamRouters.get().calcRoute(
                FacilitiesUtils.toFacility(trip.getOriginActivity(),scenario.getActivityFacilities()),
                FacilitiesUtils.toFacility(trip.getDestinationActivity(),scenario.getActivityFacilities()),
                PlanRouter.calcEndOfActivity(trip.getOriginActivity(),plan,scenario.getConfig()),person);
            if(route==null||route.stream().noneMatch(e->e instanceof Leg&&"aam_drt".equals(((Leg)e).getMode())))return false;
            for(PlanElement element:route)if(element instanceof Leg&&"aam_drt".equals(((Leg)element).getMode())){
                Leg leg=(Leg)element;Object ad=leg.getAttributes().getAttribute("aam_access_distance_m"),ed=leg.getAttributes().getAttribute("aam_egress_distance_m");
                if(ad instanceof Number)candidate.access=((Number)ad).doubleValue();if(ed instanceof Number)candidate.egress=((Number)ed).doubleValue();
                Object op=leg.getAttributes().getAttribute("aam_origin_vertiport"),dp=leg.getAttributes().getAttribute("aam_destination_vertiport");
                if(op!=null)candidate.originPort=op.toString();if(dp!=null)candidate.destinationPort=dp.toString();
            }
            TripRouter.insertTrip(plan,trip.getOriginActivity(),route,trip.getDestinationActivity());return true;
        }catch(AamMultimodalRoutingModule.InfeasibleAamRouteException expected){return false;}
        finally{person.setSelectedPlan(selected);}
    }
    private static void restore(Plan p,List<PlanElement> elements,Map<String,Object> attributes){
        p.getPlanElements().clear();p.getPlanElements().addAll(elements);
        for(String k:new ArrayList<>(p.getAttributes().getAsMap().keySet()))p.getAttributes().removeAttribute(k);
        attributes.forEach((k,v)->p.getAttributes().putAttribute(k,v));
    }
    private static final class Choice {final int first,last;final String privateMode,parking;final double cost;int homeFirst=-1,homeLast=-1;
        Choice(int first,int last,String mode,double cost,String parking){this.first=first;this.last=last;privateMode=mode;this.cost=cost;this.parking=parking;}}
    private static final class GroundTripRef {final Activity origin,destination;GroundTripRef(Activity o,Activity d){origin=o;destination=d;}}
    public void finishReplanning(){}
}
