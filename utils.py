#! /usr/bin/env python

from collections import defaultdict

from rdflib.graph import Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from structures import Clause


def generate_label_map(g):
    label_map = dict()
    for e, _, l in g.triples((None, RDFS.label, None)):
        label_map[e] = l

    return label_map

def generate_data_type_map(g):
    data_type_map = {'object-to-type': dict(),
                     'type-to-object': dict()}
    for o in g.objects():
        if type(o) is not Literal:
            continue

        dtype = o.datatype
        if dtype is None:
            dtype = XSD.string if o.language != None else XSD.anyType

        if dtype not in data_type_map.keys():
            data_type_map['type-to-object'][dtype] = set()

        data_type_map['type-to-object'][dtype].add(o)
        data_type_map['object-to-type'][o] = dtype

    return data_type_map

def generate_object_type_map(g):
    object_type_map = {'object-to-type': dict(),
                       'type-to-object': dict()}
    for e in g.subjects():
        if type(e) is not URIRef:
            continue

        ctype = g.value(e, RDF.type)
        if ctype is None:
            ctype = RDFS.Class
        if ctype not in object_type_map['type-to-object'].keys():
            object_type_map['type-to-object'][ctype] = set()

        object_type_map['type-to-object'][ctype].add(e)
        object_type_map['object-to-type'][e] = ctype

    return object_type_map

def generate_predicate_map(g):
    predicate_map = dict()

    for lhs, predicate, rhs in g.triples((None, None, None)):
        if predicate not in predicate_map.keys():
            predicate_map[predicate] = {'forwards': dict(), 'backwards': dict()}

        if lhs not in predicate_map[predicate]['forwards'].keys():
            predicate_map[predicate]['forwards'][lhs] = {rhs}
        else:
            predicate_map[predicate]['forwards'][lhs].add(rhs)

        if rhs not in predicate_map[predicate]['backwards'].keys():
            predicate_map[predicate]['backwards'][rhs] = {lhs}
        else:
            predicate_map[predicate]['backwards'][rhs].add(lhs)

    # set default value to empty set
    for predicate in predicate_map.keys():
        predicate_map[predicate] = {
            'forwards': defaultdict(lambda: set(), predicate_map[predicate]['forwards']),
            'backwards': defaultdict(lambda: set(), predicate_map[predicate]['backwards'])}

    return predicate_map

def confidence_of(predicate_map,
               object_type_map,
               data_type_map,
               assertion,
               assertion_domain):
    """ Calculate confidence for a Clause head

    Assumes that domain satisfies the Clause body that belongs to this head
    """
    confidence = 0
    assertion_domain_updated = set()
    if not isinstance(assertion.rhs, Clause.TypeVariable):
        # either an entity or literal
        for entity in assertion_domain:
            if assertion.rhs in predicate_map[assertion.predicate]['forwards'][entity]:
                # P(e, u) holds
                assertion_domain_updated.add(entity)
                confidence += 1
    elif isinstance(assertion.rhs, Clause.ObjectTypeVariable):
        for entity in assertion_domain:
            for resource in predicate_map[assertion.predicate]['forwards'][entity]:
                if object_type_map['object-to-type'][resource] is assertion.rhs.type:
                    # P(e, ?) with object type(?, t) holds
                    assertion_domain_updated.add(entity)
                    confidence += 1
    elif isinstance(assertion.rhs, Clause.DataTypeVariable):
        for entity in assertion_domain:
            for resource in predicate_map[assertion.predicate]['forwards'][entity]:
                if data_type_map['object-to-type'][resource] == assertion.rhs.type:
                    # P(e, ?) with data type(?, t) holds
                    assertion_domain_updated.add(entity)
                    confidence += 1

    return (confidence, assertion_domain_updated)

def support_of(predicate_map,
            object_type_map,
            data_type_map,
            graph_pattern,
            assertion,
            assertion_domain,
            min_support):
    """ Calculate Minimal Image-Based Support for a Clause body

    Returns -1 if support < min_support

    Optimized to minimalize the work done by continuously reducing the search
    space and by early stopping when possible
    """
    # no need to continue if we are a pendant incident (optimization)
    if len(graph_pattern.connections[assertion]) <= 0:
        if isinstance(assertion, Clause.IdentityAssertion):
            return (len(assertion_domain), assertion_domain)

        support = 0
        assertion_domain_updated = set()
        if not isinstance(assertion.rhs, Clause.TypeVariable):
            # either an entity or literal
            for entity in assertion_domain:
                if assertion.rhs in predicate_map[assertion.predicate]['forwards'][entity]:
                    # P(e, u) holds
                    assertion_domain_updated.add(entity)
                    support += 1
        elif isinstance(assertion.rhs, Clause.ObjectTypeVariable):
            for entity in assertion_domain:
                for resource in predicate_map[assertion.predicate]['forwards'][entity]:
                    if object_type_map['object-to-type'][resource] is assertion.rhs.type:
                        # P(e, ?) with object type(?, t) holds
                        assertion_domain_updated.add(entity)
                        support += 1
        elif isinstance(assertion.rhs, Clause.DataTypeVariable):
            for entity in assertion_domain:
                for resource in predicate_map[assertion.predicate]['forwards'][entity]:
                    if data_type_map['object-to-type'][resource] == assertion.rhs.type:
                        # P(e, ?) with data type(?, t) holds
                        assertion_domain_updated.add(entity)
                        support += 1

        return (support, assertion_domain_updated)

    # retrieve range based on assertion's domain
    if isinstance(assertion, Clause.IdentityAssertion):
        assertion_range = assertion_domain
    else:  # type is Clause.Assertion with ObjectTypeVariable as rhs
        assertion_range = set()
        for entity in assertion_domain:
            for resource in predicate_map[assertion.predicate]['forwards'][entity]:
                if object_type_map['object-to-type'][resource] is assertion.rhs.type:
                    assertion_range.add(resource)

    # update range based on connected assertions' domains (optimization)
    for connection in graph_pattern.connections[assertion]:
        if len(assertion_range) < min_support:
            return (-1, set())

        assertion_range &= frozenset(predicate_map[connection.predicate]['forwards'].keys())

    # update range based on connected assertions' returned updated domains
    # search space is reduced after each returned update
    connection_domain = assertion_range  # only for readability
    for connection in graph_pattern.connections[assertion]:
        if len(assertion_range) < min_support:
            return (-1, set())

        support, range_update = support_of(predicate_map,
                                        object_type_map,
                                        data_type_map,
                                        graph_pattern,
                                        connection,
                                        connection_domain,
                                        min_support)
        if support < min_support:
            return (-1, set())

        assertion_range &= range_update

    # update domain based on updated range
    if isinstance(assertion, Clause.IdentityAssertion):
        return (len(assertion_range), assertion_range)

    support = 0
    assertion_domain_updated = set()
    for resource in assertion_range:
        domain_update = predicate_map[assertion.predicate]['backwards'][resource]
        assertion_domain_updated |= domain_update

        support += len(domain_update)

    return (support, assertion_domain_updated)