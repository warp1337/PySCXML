''' 
This file is part of pyscxml.

    PySCXML is free software: you can redistribute it and/or modify
    it under the terms of the GNU Lesser General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    PySCXML is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Lesser General Public License for more details.

    You should have received a copy of the GNU Lesser General Public License
    along with PySCXML.  If not, see <http://www.gnu.org/licenses/>.
    
    This is an implementation of the interpreter algorithm described in the W3C standard document, 
    which can be found at:
    
    http://www.w3.org/TR/2009/WD-scxml-20091029/ 
    
    @author Johan Roxendal
    @contact: johan@roxendal.com
'''


from node import *

from datastructures import OrderedSet
from eventprocessor import Event
from louie import dispatcher
from scxml.eventprocessor import ScxmlOriginType
import eventlet
from eventlet import Queue
from scxml.datamodel import ECMAScriptDataModel


class Interpreter(object):
    '''
    The class repsonsible for keeping track of the execution of the 
    statemachine.
    '''
    def __init__(self):
        self.running = True
        self.exited = False
        self.cancelled = False
        self.configuration = OrderedSet()
        
        self.internalQueue = Queue()
        self.externalQueue = Queue()
        
        self.statesToInvoke = OrderedSet()
        self.historyValue = {}
        self.dm = None
        self.invokeId = None
        self.parentId = None
        self.logger = None
    
    
    def interpret(self, document, invokeId=None):
        '''Initializes the interpreter given an SCXMLDocument instance'''
        
        self.doc = document
        self.invokeId = invokeId
        
        transition = Transition(document.rootState)
        transition.target = document.rootState.initial
        transition.exe = document.rootState.initial.exe
        
        self.executeTransitionContent([transition])
        self.enterStates([transition])
        
    
    
    def mainEventLoop(self):
        while self.running:
            enabledTransitions = None
            stable = False
                
            # now take any newly enabled null transitions and any transitions triggered by internal events
            while self.running and not stable:
                enabledTransitions = self.selectEventlessTransitions()
                if not enabledTransitions:
                    if self.internalQueue.empty(): 
                        stable = True
                    else:
                        internalEvent = self.internalQueue.get() # this call returns immediately if no event is available
                        
                        self.logger.info("internal event found: %s", internalEvent.name)
                        
                        self.dm["__event"] = internalEvent
                        enabledTransitions = self.selectTransitions(internalEvent)

                if enabledTransitions:
                    self.microstep(enabledTransitions)
#                eventlet.greenthread.sleep()
            eventlet.greenthread.sleep()
                
                    
            
            for state in self.statesToInvoke:
                for inv in state.invoke:
                    inv.invoke(inv)
            self.statesToInvoke.clear()
            
            if not self.internalQueue.empty():
                continue
            
            externalEvent = self.externalQueue.get() # this call blocks until an event is available
            
#            if externalEvent.name == "cancel.invoke.%s" % self.dm.sessionid:
#                continue

            # our parent session also might cancel us.  The mechanism for this is platform specific,
            if isCancelEvent(externalEvent):
                self.running = False
                continue
            
            # self.logger.info("external event found: %s", externalEvent.name)
            
            self.dm["__event"] = externalEvent
            
            for state in self.configuration:
                for inv in state.invoke:
                    if inv.invokeid == externalEvent.invokeid:  # event is the result of an <invoke> in this state
                        self.applyFinalize(inv, externalEvent)
                    if inv.autoforward:
                        inv.send(externalEvent)
            
            enabledTransitions = self.selectTransitions(externalEvent)
            if enabledTransitions:
                self.microstep(enabledTransitions)
            
              
        # if we get here, we have reached a top-level final state or some external entity has set running to False        
        self.exitInterpreter()  
         
    
        
    def exitInterpreter(self):
        statesToExit = sorted(self.configuration, key=exitOrder)
        for s in statesToExit:
            for content in s.onexit:
                self.executeContent(content)
            for inv in s.invoke:
                self.cancelInvoke(inv)
            self.configuration.delete(s)
            if isFinalState(s) and isScxmlState(s.parent):
                if self.invokeId and self.parentId and self.parentId in self.dm.sessions:
                    self.send(["done", "invoke", self.invokeId], s.donedata(), self.invokeId, self.dm.sessions[self.parentId].interpreter.externalQueue)   
                self.logger.info("Exiting interpreter")
                dispatcher.send("signal_exit", self, final=s.id)
                self.exited = True
                return
        self.exited = True
        dispatcher.send("signal_exit", self, final=None)
            
        
    def selectEventlessTransitions(self):
        enabledTransitions = OrderedSet()
        atomicStates = filter(isAtomicState, self.configuration)
        atomicStates = sorted(atomicStates, key=documentOrder)
        for state in atomicStates:
            done = False
            for s in [state] + getProperAncestors(state, None):
                if done: break
                for t in s.transition:
                    if not t.event and self.conditionMatch(t): 
                        enabledTransitions.add(t)
                        done = True
                        break
        filteredTransitions = self.filterPreempted(enabledTransitions)
        return filteredTransitions
    
    
    def selectTransitions(self, event):
        enabledTransitions = OrderedSet()
        atomicStates = filter(isAtomicState, self.configuration)
        atomicStates = sorted(atomicStates, key=documentOrder)

        for state in atomicStates:
            done = False
            for s in [state] + getProperAncestors(state, None):
                if done: break
                for t in s.transition:
                    if t.event and nameMatch(t.event, event.name.split(".")) and self.conditionMatch(t):
                        enabledTransitions.add(t)
                        done = True
                        break
                    
        filteredTransitions = self.filterPreempted(enabledTransitions)
        return filteredTransitions
    
    
    def preemptsTransition(self, t, t2):
        
        if self.isType1(t): return False
        elif self.isType2(t) and self.isType3(t2): return True
        elif self.isType3(t): return True
        
        return False
    
    def findLCPA(self, states):
        '''
        Gets the least common parallel ancestor of states. 
        Just like findLCA but only for parallel states.
        '''
        for anc in filter(isParallelState, getProperAncestors(states[0], None)):
            if all(map(lambda(s): isDescendant(s,anc), states[1:])):
                return anc
    
    
    def isType1(self, t):
        return not t.target
    
    def isType2(self, t):
        source = t.source if t.type == "internal" else t.source.parent
        p = self.findLCPA([source] + self.getTargetStates(t.target))
        return p is not None
            
    
    def isType3(self, t):
        return not self.isType2(t) and not self.isType1(t)
    
    
    def filterPreempted(self, enabledTransitions):
        filteredTransitions = []
        for t in enabledTransitions:
            # does any t2 in filteredTransitions preempt t? if not, add t to filteredTransitions
            if not any(map(lambda t2: self.preemptsTransition(t2, t), filteredTransitions)):
                filteredTransitions.append(t)
        
        return OrderedSet(filteredTransitions)
    
    
    def microstep(self, enabledTransitions):
        self.exitStates(enabledTransitions)
        self.executeTransitionContent(enabledTransitions)
        self.enterStates(enabledTransitions)
        # self.logger.info("new config: {" + ", ".join([s.id for s in self.configuration if s.id != "__main__"]) + "}")
    
    
    def exitStates(self, enabledTransitions):
        statesToExit = OrderedSet()
        for t in enabledTransitions:
            if t.target:
                tstates = self.getTargetStates(t.target)
                if t.type == "internal" and isCompoundState(t.source) and all(map(lambda s: isDescendant(s,t.source), tstates)):
                    ancestor = t.source
                else:
                    ancestor = self.findLCA([t.source] + tstates)
                
                for s in self.configuration:
                    if isDescendant(s,ancestor):
                        statesToExit.add(s)
        
        for s in statesToExit:
            self.statesToInvoke.delete(s)
        
        statesToExit.sort(key=exitOrder)
        
        for s in statesToExit:
            for h in s.history:
                if h.type == "deep":
                    f = lambda s0: isAtomicState(s0) and isDescendant(s0,s)
                else:
                    f = lambda s0: s0.parent == s
                self.historyValue[h.id] = filter(f,self.configuration) #+ s.parent 
        for s in statesToExit:
            for content in s.onexit:
                self.executeContent(content)
            for inv in s.invoke:
                self.cancelInvoke(inv)
            self.configuration.delete(s)
    
        
    def cancelInvoke(self, inv):
        inv.cancel()
    
    def executeTransitionContent(self, enabledTransitions):
        for t in enabledTransitions:
            self.executeContent(t)
    
    
    def enterStates(self, enabledTransitions):
        statesToEnter = OrderedSet()
        statesForDefaultEntry = OrderedSet()
        for t in enabledTransitions:
            if t.target:
                tstates = self.getTargetStates(t.target)
                if t.type == "internal" and isCompoundState(t.source) and all(map(lambda s: isDescendant(s,t.source), tstates)):
                    ancestor = t.source
                else:
                    ancestor = self.findLCA([t.source] + tstates)
                for s in tstates:
                    self.addStatesToEnter(s,statesToEnter,statesForDefaultEntry)
                for s in tstates:
                    for anc in getProperAncestors(s,ancestor):
                        statesToEnter.add(anc)
                        if isParallelState(anc):
                            for child in getChildStates(anc):
                                if not any(map(lambda s: isDescendant(s,child), statesToEnter)):
                                    self.addStatesToEnter(child, statesToEnter,statesForDefaultEntry)

        statesToEnter.sort(key=enterOrder)
        for s in statesToEnter:
            self.statesToInvoke.add(s)
            self.configuration.add(s)
            if self.doc.binding == "late" and s.isFirstEntry:
                s.initDatamodel()
                s.isFirstEntry = False

            for content in s.onentry:
                self.executeContent(content)
            if s in statesForDefaultEntry:
                self.executeContent(s.initial)
            if isFinalState(s):
                parent = s.parent
                grandparent = parent.parent
                self.internalQueue.put(Event(["done", "state", parent.id], s.donedata()))
                if isParallelState(grandparent):
                    if all(map(self.isInFinalState, getChildStates(grandparent))):
                        self.internalQueue.put(Event(["done", "state", grandparent.id]))
        for s in self.configuration:
            if isFinalState(s) and isScxmlState(s.parent):
                self.running = False;
    
    
    def addStatesToEnter(self, state,statesToEnter,statesForDefaultEntry):
        if isHistoryState(state):
            if state.id in self.historyValue:
                for s in self.historyValue[state.id]:
                    self.addStatesToEnter(s, statesToEnter, statesForDefaultEntry)
                    for anc in getProperAncestors(s,state):
                        statesToEnter.add(anc)
            else:
                for t in state.transition:
                    for s in self.getTargetStates(t.target):
                        self.addStatesToEnter(s, statesToEnter, statesForDefaultEntry)
        else:
            statesToEnter.add(state)
            if isCompoundState(state):
                statesForDefaultEntry.add(state)
                for s in self.getTargetStates(state.initial):
                    self.addStatesToEnter(s, statesToEnter, statesForDefaultEntry)
            elif isParallelState(state):
                for s in getChildStates(state):
                    self.addStatesToEnter(s,statesToEnter,statesForDefaultEntry)
    
    def isInFinalState(self, s):
        if isCompoundState(s):
            return any(map(lambda s: isFinalState(s) and s in self.configuration, getChildStates(s)))
        elif isParallelState(s):
            return all(map(self.isInFinalState, getChildStates(s)))
        else:
            return False
    
    def findLCA(self, stateList):
        for anc in filter(isCompoundState, getProperAncestors(stateList[0], None)):
            if all(map(lambda(s): isDescendant(s,anc), stateList[1:])):
                return anc
    
    
    def applyFinalize(self, inv, event):
        inv.finalize()
    
    def getTargetStates(self, targetIds):
        if targetIds == None:
            pass
        states = []
        for id in targetIds:
            state = self.doc.getState(id)
            if not state:
                raise Exception("The target state '%s' does not exist" % id)
            states.append(state)
        return states
    
    def executeContent(self, obj):
        if hasattr(obj, "exe") and callable(obj.exe):
            obj.exe()
    
    def conditionMatch(self, t):
        if not t.cond:
            return True
        else:
            return t.cond()
                
    def In(self, name):
        return name in map(lambda x: x.id, self.configuration)
    
    
    def send(self, name, data=None, invokeid = None, toQueue = None, sendid=None, eventtype="platform", raw=None, language=None):
        """Send an event to the statemachine 
        @param name: a dot delimited string, the event name
        @param data: the data associated with the event
        @param invokeid: if specified, the id of sending invoked process
        @param toQueue: if specified, the target queue on which to add the event
        
        """
        if isinstance(name, basestring): name = name.split(".")
        if not toQueue: toQueue = self.externalQueue
        evt = Event(name, data, invokeid, sendid=sendid, eventtype=eventtype)
        evt.origin = "#_scxml_" + self.dm.sessionid
        evt.origintype = ScxmlOriginType() if not isinstance(self.dm, ECMAScriptDataModel) else "http://www.w3.org/TR/scxml/#SCXMLEventProcessor"
        evt.raw = raw
        #TODO: and for ecmascript?
        evt.language =  language
        toQueue.put(evt)
        
            
    def raiseFunction(self, event, data, sendid=None, type="internal"):
        e = Event(event, data, eventtype=type, sendid=sendid)
        e.origintype = None
        self.internalQueue.put(e)


def getProperAncestors(state,root):
#    ancestors = [root] if root else []
    ancestors = []
    while hasattr(state,'parent') and state.parent and state.parent != root:
        state = state.parent
        ancestors.append(state)
    return ancestors
    
    
def isDescendant(state1,state2):
    while hasattr(state1,'parent'):
        state1 = state1.parent
        if state1 == state2:
            return True
    return False

def getChildStates(state):
    return state.state + state.final + state.history


def nameMatch(eventList, event):
    if ["*"] in eventList: return True 
    def prefixList(l1, l2):
        if len(l1) > len(l2): return False 
        for tup in zip(l1, l2):
            if tup[0] != tup[1]:
                return False 
        return True 
    
    for elem in eventList:
        if prefixList(elem, event):
            return True 
    return False 

##
## Various tests for states
##

def isParallelState(s):
    return isinstance(s,Parallel)


def isFinalState(s):
    return isinstance(s,Final)


def isHistoryState(s):
    return isinstance(s,History)


def isScxmlState(s):
    return s.parent == None


def isAtomicState(s):
    return isinstance(s, Final) or (isinstance(s,SCXMLNode) and s.state == [] and s.final == [])


def isCompoundState(s):
    return (isinstance(s,State) and (s.state != [] or s.final != []) ) or s.parent is None #incluce root state


def enterOrder(s):
    return s.n  

def exitOrder(s):
    return 0 - s.n

def documentOrder(s):
    key = [s.n]
    p = s.parent
    while p.n:
        key.append(p.n)
        p = p.parent
    key.reverse()
    return key


class CancelEvent(object):
    pass    
def isCancelEvent(evt):
    return isinstance(evt, CancelEvent)    

