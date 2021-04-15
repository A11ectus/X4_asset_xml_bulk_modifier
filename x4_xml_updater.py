# -*- coding: utf-8 -*-
"""
Created on Thu Mar 11 22:14:51 2021

@author: Allectus
"""

import os
import re
import copy
import pandas as pd
import tkinter as tk

import plotly.io as pio
import plotly.express as px

from tkinter import filedialog
from lxml import etree

#==============================================================================

def parse_asset_file(xmlfile, taglist, convert=True, collapse_diffs=True):
    #Parses X4:Foundations asset xml files
    #
    #xmlfile: file path to desired input asset file
    #taglist: XML asset property tag to collect attributes for
    #convert: If True attributes will be converted to floats

    xtree = etree.parse(xmlfile)

    result = {}
    for attr in taglist:
        
        attr_element = xtree.find('//' + str(attr))
        
        if attr_element is not None:
            attr_path = xtree.getpath(attr_element)
            
            
            if collapse_diffs:
                attr_path = re.sub(r'/diff/(replace|add)', '', attr_path)
            
            if attr_element is None: 
                attr_dict = {} 
            else: 
                attr_dict = {str(attr_path) + '/' +  str(k):v for k,v in attr_element.attrib.items()}
            
            if convert:
                attr_dict = {k:float(v) for k,v in attr_dict.items()}
        else:
            attr_dict = {}
        
        result.update(attr_dict)

    return(result)

#------------------------------------------------------------------------------

def export_asset_xml_diff(outfilepath, attributes):
    #Exports X4:Foundations asset diff xml files
    #
    #outfilepath: file path to desired output file
    #attributes: dict of xpath:value to be exported in the diff file

    attributes

    outstr = '\n'.join(['<?xml version="1.0" encoding="utf-8"?>',
                        '<diff>',
                        '  <replace sel="' + 
                          '\n  <replace sel="'.join([str(xpath)[:str(xpath).rfind('/') + 1] + '@' + 
                                                     str(xpath)[str(xpath).rfind('/') + 1:] + '">' + 
                                                     str(round(val,2)) + '</replace>' 
                                                     for xpath,val in attributes.items()]),
                        '</diff>'])
    
    os.makedirs(os.path.dirname(outfilepath), exist_ok=True)
    
    with open(outfilepath, 'w') as outfile:
        outfile.write(outstr)
        
    return(True)

#------------------------------------------------------------------------------

def parse_resources(resources, asset_path, file_pattern, taglist):
    #Collects and parses relevant X4:Foundations asset files based upon input filters
    #
    #resources: pd.DataFrame of available unpacked input directories, contains resources root
    #asset_path: path to relevant directory for the specific asset, relative to resource root
    #file_pattern: regex pattern to id files in asset path to retain
    #taglist: tags to extract from the identied input files

    loc_resources = copy.deepcopy(resources)

    #Find game files
    loc_resources['assetdir'] = loc_resources.root.apply(lambda x: os.path.join(x, asset_path)) 
    loc_resources['filelist'] = loc_resources.assetdir.apply(os.listdir)
    loc_resources = loc_resources.explode('filelist', ignore_index=True)

    #Filter out unwanted files (only keep appropriate xml files)
    loc_resources.rename(columns={'filelist':'basefilename'}, inplace=True)
    loc_resources['keep'] = loc_resources.basefilename.apply(lambda x: os.path.splitext(x)[1] == '.xml') & loc_resources.basefilename.str.contains(file_pattern)
    loc_resources = loc_resources[loc_resources.keep].reset_index(drop=True) 
    loc_resources = loc_resources.drop('keep', axis=1)
    loc_resources['fullpath'] = loc_resources.apply(lambda x: os.path.join(x['assetdir'], x['basefilename']), axis=1)
    
    #Parse the discovered files
    loc_resources = pd.concat([loc_resources, pd.DataFrame(list(loc_resources['fullpath'].apply(
        lambda x: parse_asset_file(x, taglist=taglist, convert=True, collapse_diffs=True))))], axis=1)
        
    return(loc_resources)

#------------------------------------------------------------------------------

def update_shields(resources, asset_path = 'assets/props/SurfaceElements/macros', 
                   file_pattern=r'^shield.*', taglist = ['recharge']):
    #Identifies and modified X4: Foundations shield files
    #
    #resources: pd.DataFrame of available unpacked input directories, contains resources root
    #asset_path: path to relevant directory for the specific asset, relative to resource root
    #file_pattern: regex pattern to id files in asset path to retain
    #taglist: tags to extract from the identied input files    
    
    shield_resources = parse_resources(resources=resources, asset_path=asset_path, 
                                       file_pattern=file_pattern, taglist=taglist)

    #capture owner/size/type from filename
    shield_metadata = shield_resources.basefilename.str.extract(r'(shield_)(.*)(_)(s|m|l|xl)(_)(.*)(_.*)(mk.)(.*)', expand=True)
    shield_metadata = shield_metadata.rename(columns={1:'race', 3:'size', 5:'type', 7:'mk'})
    shield_resources = pd.concat([shield_resources, shield_metadata[['race', 'size', 'type', 'mk']]], axis=1)  
    
    #colname look up table (to retain xpath in colname so we dont have to reshape to long format)
    #gives 'tag_attrib': xpath
    modified_cols = {}
    cnm_init = {}
    for tag in taglist:
        colpattern = r'.*(/' + str(tag) + r'/).*'
        cnm_init.update({str(tag)+'_'+str(c)[str(c).rfind('/')+1:] :c for c in shield_resources.columns if re.match(colpattern, c)})
    
    vro_results = shield_resources[(shield_resources['source'] == 'vro')].reset_index()
    base_results = shield_resources[(shield_resources['source'] == 'base')].reset_index()

    modified = pd.merge(vro_results, base_results, how='left', on=['race', 'size', 'type', 'mk'], suffixes=['_vro', '_base'])
    
    #update colname map
    cnm = copy.deepcopy(cnm_init)
    cnm.update({str(k)+'_base':str(v)+'_base' for k, v in cnm_init.items()}) 
    cnm.update({str(k)+'_vro':str(v)+'_vro' for k, v in cnm_init.items()}) 
    
    #modify values
    max_factors = modified.groupby(['size', 'mk']).apply(lambda x: (x[cnm['recharge_max_vro']] / x[cnm['recharge_max_base']]).mean()).reset_index()
    max_factors.rename(columns={0:'max_factor'}, inplace=True)
    modified = modified.merge(max_factors, how='left', on=['size', 'mk'])
    modified[cnm['recharge_max']] = modified[cnm['recharge_max_base']] * modified['max_factor']
    modified.loc[(modified['race'].isin(['kha'])) | (modified[cnm['recharge_max']].isna()), cnm['recharge_max']] = modified[cnm['recharge_max_vro']]
    modified_cols.update({'recharge_max': cnm['recharge_max']})

    modified[cnm['recharge_delay']] = modified[cnm['recharge_delay_base']] * (3/2)
    modified.loc[(modified['race'].isin(['kha'])) | (~modified['size'].isin(['s'])) | (modified[cnm['recharge_delay']].isna()), cnm['recharge_delay']] = modified[cnm['recharge_delay_vro']]
    modified_cols.update({'recharge_delay': cnm['recharge_delay']})
    
    recharge_factors = modified.groupby(['size', 'mk']).apply(lambda x: (x[cnm['recharge_rate_vro']] / x[cnm['recharge_rate_base']]).mean()).reset_index()
    recharge_factors.rename(columns={0:'recharge_factor'}, inplace=True)
    modified = modified.merge(recharge_factors, how='left', on=['size', 'mk'])
    modified[cnm['recharge_rate']] = modified[cnm['recharge_rate_base']] * modified['recharge_factor']
    modified.loc[modified['size'].isin(['s']), cnm['recharge_rate']] = modified[cnm['recharge_rate_base']] * 0.9
    modified.loc[modified['size'].isin(['m']), cnm['recharge_rate']] = modified[cnm['recharge_rate_base']] * modified['recharge_factor'] * 1.25
    modified.loc[(modified['race'].isin(['kha'])) | (modified[cnm['recharge_rate']].isna()), cnm['recharge_rate']] = modified[cnm['recharge_rate_vro']]
    modified_cols.update({'recharge_rate':cnm['recharge_rate']})
    
    return(modified, modified_cols)

#------------------------------------------------------------------------------

def update_engines(resources, asset_path = 'assets/props/Engines/macros', 
                   file_pattern=r'^engine.*', taglist = ['thrust', 'boost', 'travel']):
    #Identifies and modified X4: Foundations engine files
    #
    #resources: pd.DataFrame of available unpacked input directories, contains resources root
    #asset_path: path to relevant directory for the specific asset, relative to resource root
    #file_pattern: regex pattern to id files in asset path to retain
    #taglist: tags to extract from the identied input files    
    
    engine_resources = parse_resources(resources=resources, asset_path=asset_path, 
                                       file_pattern=file_pattern, taglist=taglist)

    #capture owner/size/type from filename
    engine_metadata = engine_resources.basefilename.str.extract(r'(engine_)(.*)(_)(s|m|l|xl)(_)(.*)(_.*)(mk.)(.*)', expand=True)
    engine_metadata = engine_metadata.rename(columns={1:'race', 3:'size', 5:'type', 7:'mk'})
    engine_resources = pd.concat([engine_resources, engine_metadata[['race', 'size', 'type', 'mk']]], axis=1)  
    
    #colname look up table (to retain xpath in colname so we dont have to reshape to long format)
    #gives 'tag_attrib': xpath
    modified_cols = {}
    cnm_init = {}
    for tag in taglist:
        colpattern = r'.*(/' + str(tag) + r'/).*'
        cnm_init.update({str(tag)+'_'+str(c)[str(c).rfind('/')+1:] :c for c in engine_resources.columns if re.match(colpattern, c)})
    
    #Further filter observations to only those with travel stats (eliminate thrusters etc)
    engine_resources = engine_resources[~engine_resources[cnm_init['travel_thrust']].isna()].reset_index(drop=True)

    engine_resources['eff_boost_thrust'] = engine_resources[cnm_init['thrust_forward']] * engine_resources[cnm_init['boost_thrust']]
    engine_resources['eff_travel_thrust'] = engine_resources[cnm_init['thrust_forward']] * engine_resources[cnm_init['travel_thrust']]
    
    vro_results = engine_resources[(engine_resources['source'] == 'vro')].reset_index()
    base_results = engine_resources[(engine_resources['source'] == 'base')].reset_index()

    modified = pd.merge(vro_results, base_results, how='left', on=['race', 'size', 'type', 'mk'], suffixes=['_vro', '_base'])
    
    #update colname map
    cnm = copy.deepcopy(cnm_init)
    cnm.update({str(k)+'_base':str(v)+'_base' for k, v in cnm_init.items()}) 
    cnm.update({str(k)+'_vro':str(v)+'_vro' for k, v in cnm_init.items()}) 
    
    #modify values
    
    #Calculate average conversion factors for vro <-> base thrust to allow us to normalize new engines
    thrust_factors = modified.groupby(['size', 'mk', 'type']).apply(lambda x: (x[cnm['thrust_forward_vro']] / x[cnm['thrust_forward_base']]).mean()).reset_index()
    thrust_factors.rename(columns={0:'thrust_factor'}, inplace=True)
    modified = modified.merge(thrust_factors, how='left', on=['size', 'mk', 'type'])

    attack_factors = modified.groupby(['size', 'mk', 'type']).apply(lambda x: (x[cnm['travel_attack_vro']] / x[cnm['travel_attack_base']]).mean()).reset_index()
    attack_factors.rename(columns={0:'attack_factor'}, inplace=True)
    modified = modified.merge(attack_factors, how='left', on=['size', 'mk', 'type'])
    
    #Calculate effective normalized thrust values
    modified['thrust_forward_pre'] = modified[cnm['thrust_forward_vro']]

    modified['boost_thrust_pre'] = modified['eff_boost_thrust_base'] / modified['thrust_forward_pre']
    modified.loc[modified['boost_thrust_pre'].isna(), 'boost_thrust_pre'] = modified['eff_boost_thrust_vro'] / ( modified[cnm['thrust_forward_vro']] / modified['thrust_factor'])
    modified['travel_thrust_pre'] = modified['eff_travel_thrust_base'] / modified['thrust_forward_pre']
    modified.loc[modified['travel_thrust_pre'].isna(), 'travel_thrust_pre'] = modified['eff_travel_thrust_vro'] / ( modified[cnm['thrust_forward_vro']] / modified['thrust_factor'])
    
    modified['eff_boost_thrust_pre'] = modified['thrust_forward_pre'] * modified['boost_thrust_pre']
    modified['eff_travel_thrust_pre'] = modified['thrust_forward_pre'] * modified['travel_thrust_pre']
    
    #Create initial boost and travel thrust rankings so we can match them later
    modified.sort_values(['size', 'thrust_forward_pre'], inplace=True)
    modified['travel_rank'] = modified.groupby('size')['eff_travel_thrust_pre'].rank(axis=1, ascending=False, method='first')
    modified['boost_rank'] = modified.groupby('size')['eff_boost_thrust_pre'].rank(axis=1, ascending=False, method='first')
    modified = pd.merge(modified, modified, left_on=['size', 'travel_rank'], right_on=['size', 'boost_rank'], suffixes=['_original', '_ranked'] )
        
    #update name mapping
    cnm.update({str(k)+'_base_original':str(v)+'_base_original' for k, v in cnm_init.items()}) 
    cnm.update({str(k)+'_base_ranked':str(v)+'_base_ranked' for k, v in cnm_init.items()}) 
    cnm.update({str(k)+'_vro_original':str(v)+'_vro_original' for k, v in cnm_init.items()}) 
    cnm.update({str(k)+'_vro_ranked':str(v)+'_vro_ranked' for k, v in cnm_init.items()}) 
    
    #-------------------------------------------------------------------------

    #calculate final engine params based upon relative base boost and travel rank
    modified[cnm['thrust_forward']] = modified[cnm['thrust_forward_vro_original']]
    modified_cols.update({'thrust_forward': cnm['thrust_forward']})

    modified[cnm['thrust_reverse']] = modified[cnm['thrust_reverse_base_original']] * modified['thrust_factor_original']
    modified.loc[modified[cnm['thrust_reverse']].isna(), cnm['thrust_reverse']] = modified[cnm['thrust_reverse_vro_original']]
    modified_cols.update({'thrust_reverse': cnm['thrust_reverse']})
    
    modified['eff_boost_thrust'] = modified['eff_boost_thrust_pre_original']
    modified[cnm['boost_thrust']] = modified['eff_boost_thrust'] / modified[cnm['thrust_forward']]
    modified_cols.update({'boost_thrust': cnm['boost_thrust']})
    
    modified[cnm['boost_duration']] = modified[cnm['boost_duration_base_original']]
    modified.loc[modified[cnm['boost_duration']].isna(), cnm['boost_duration']] = modified[cnm['boost_duration_vro_original']] / modified['attack_factor_original']    
    modified_cols.update({'boost_duration': cnm['boost_duration']})
    
    modified[cnm['boost_attack']] = modified[cnm['boost_attack_base_original']]
    modified.loc[modified[cnm['boost_attack']].isna(), cnm['boost_attack']] = modified[cnm['boost_attack_vro_original']] / modified['attack_factor_original']    
    modified_cols.update({'boost_attack': cnm['boost_attack']})
    
    modified[cnm['boost_release']] = modified[cnm['boost_release_base_original']]
    modified.loc[modified[cnm['boost_release']].isna(), cnm['boost_release']] = modified[cnm['boost_release_vro_original']] / modified['attack_factor_original']    
    modified_cols.update({'boost_release': cnm['boost_release']})
    
    modified.loc[(modified['race_original'].isin(['par'])) & (modified['size'].isin(['l', 'xl'])), cnm['boost_duration']] = modified[cnm['boost_duration']] * 2
    modified.loc[(modified['race_original'].isin(['spl'])) & (modified['size'].isin(['l', 'xl'])) , cnm['boost_attack']] = modified[cnm['boost_attack']] * 0.5
    modified.loc[(modified['race_original'].isin(['spl'])) & (modified['size'].isin(['l', 'xl'])) , cnm['boost_release']] = modified[cnm['boost_release']] * 0.5
    modified.loc[(modified['race_original'].isin(['arg', 'tel'])) & (modified['size'].isin(['l', 'xl'])), cnm['boost_duration']] = modified[cnm['boost_duration']] * 1.33
    modified.loc[(modified['race_original'].isin(['arg', 'tel'])) & (modified['size'].isin(['l', 'xl'])) , cnm['boost_attack']] = modified[cnm['boost_attack']] * 0.75
    modified.loc[(modified['race_original'].isin(['arg', 'tel'])) & (modified['size'].isin(['l', 'xl'])) , cnm['boost_release']] = modified[cnm['boost_release']] * 0.75
    
    modified['eff_travel_thrust'] = modified['eff_travel_thrust_pre_original']
    modified.loc[modified['size'].isin(['s', 'm']), 'eff_travel_thrust'] = modified['eff_boost_thrust_pre_ranked']
    modified.loc[modified['size'].isin(['l', 'xl']), 'eff_travel_thrust'] = modified['eff_travel_thrust'] * (5/3)          
    modified[cnm['travel_thrust']] = modified['eff_travel_thrust'] / modified[cnm['thrust_forward']]
    modified_cols.update({'travel_thrust': cnm['travel_thrust']})
    
    modified[cnm['travel_charge']] = modified[cnm['travel_charge_base_original']]
    modified.loc[modified[cnm['travel_charge']].isna(), cnm['travel_charge']] = modified[cnm['travel_charge_vro_original']] / modified['attack_factor_original']    
    modified_cols.update({'travel_charge': cnm['travel_charge']})
    
    modified[cnm['travel_attack']] = modified[cnm['travel_attack_base_original']]
    modified.loc[modified[cnm['travel_attack']].isna(), cnm['travel_attack']] = modified[cnm['travel_attack_vro_original']] / modified['attack_factor_original']        
    modified_cols.update({'travel_attack': cnm['travel_attack']})
    
    modified[cnm['travel_release']] = modified[cnm['travel_release_base_original']]
    modified.loc[modified[cnm['travel_release']].isna(), cnm['travel_release']] = modified[cnm['travel_release_vro_original']] / modified['attack_factor_original']
    modified_cols.update({'travel_release': cnm['travel_release']})    
           
    modified.loc[(modified['race_original'].isin(['ter'])) & (modified['size'].isin(['l', 'xl'])), cnm['travel_charge']] = modified[cnm['travel_charge']] * 0.75
    
    return(modified, modified_cols)

#==============================================================================

if __name__ == "__main__":
    
    pd.options.plotting.backend = "plotly"
    pio.renderers.default ='browser'
    
    #Params    
    #Output (mod) directories
    sum_outdir = '.'
    
    mod_shields = True
    outdir_shields = 'F:/Steam/steamapps/common/X4 Foundations/extensions/al_shieldmod_vro'
    
    mod_engines = True
    outdir_engines = 'F:/Steam/steamapps/common/X4 Foundations/extensions/al_travelmod_vro'
        
    #Unpacked root directories
    base_root = 'F:/Games/Mods/x4_extracted'    
    vro_root = 'F:/Games/Mods/x4_extracted/extensions/vro' 
    
    #List of expansions to consider
    resource_list = ['base', 'split', 'terran', 'vro_base']
    
    #Hardcoded inputs for convenience
    resources = pd.DataFrame(resource_list, columns=['resource'])
    resources.loc[resources.resource == 'base', 'root'] = base_root
    resources.loc[resources.resource == 'split', 'root'] = 'F:/Games/Mods/x4_extracted/extensions/ego_dlc_split'
    resources.loc[resources.resource == 'terran', 'root'] = 'F:/Games/Mods/x4_extracted/extensions/ego_dlc_terran'
    resources.loc[resources.resource == 'vro_base', 'root'] = vro_root

    #Gather inputs for all expansions interactively if not hardcoded above
    root = tk.Tk()
    root.withdraw()    
    for grp in resource_list:
        
        missingvals = resources.loc[resources['resource'] == grp, 'root'].isna()
        if any(missingvals) or len(missingvals) == 0:
            resources.loc[resources['resource'] == grp, 'root'] = filedialog.askdirectory(title=str(grp) + " dir")
                
    #provide paths to vro expansion files given base game expansions identified in resource_list
    for grp in resource_list:
        vro_grp = 'vro_' + str(grp)
        if (grp not in ['base', 'vro_base']) and (vro_grp not in resources.resource.unique()):
            
            resources = resources.append({'resource':vro_grp, 
                                          'root':os.path.join(resources.loc[resources.resource=='vro_base', 'root'].values[0], 
                                                              'extensions', 
                                                              os.path.split(resources.loc[resources.resource==grp, 'root'].values[0])[1])}, 
                                         ignore_index=True)
    
    #Set source base vs vro input metadata
    resources['source'] = 'base'                                          
    resources.loc[resources.resource.str.contains(r'^vro_.*'), 'source'] = 'vro'
    
    #--------------------------------------------------------------------------
    
    #Modify shield parameters
    if mod_shields:
        modified_shields, modified_shields_colmap = update_shields(resources=resources)
        modified_shields['fullpath_final'] = modified_shields['fullpath_vro'].str.replace(vro_root, outdir_shields)
        
        #Export diff files
        modified_shields.apply(lambda x: export_asset_xml_diff(outfilepath = x['fullpath_final'], 
                                                               attributes = x[modified_shields_colmap.values()].to_dict()),
                               axis=1)    

        #Validation
        shields_fig = px.scatter(modified_shields, 
                                 x=modified_shields_colmap['recharge_delay'], 
                                 y=modified_shields_colmap['recharge_rate'], 
                                 text='basefilename_vro')
        shields_fig.update_traces(textposition='top center')
        shields_fig.update_layout(
                height=800,
                title_text='Recharge delay vs rate'
                )
        shields_fig.show()
        shields_fig.write_image(os.path.join(sum_outdir, 'modified_shields.png'))
        
        modified_shields.to_csv(os.path.join(sum_outdir, 'modified_shields.csv'))    
    
    #--------------------------------------------------------------------------
    
    #Modify engine parameters
    if mod_engines:
        modified_engines, modified_engines_colmap = update_engines(resources=resources)
        modified_engines['fullpath_final'] = modified_engines['fullpath_vro_original'].str.replace(vro_root, outdir_engines)
        
        #Export diff files
        modified_engines.apply(lambda x: export_asset_xml_diff(outfilepath = x['fullpath_final'], 
                                                               attributes = x[modified_engines_colmap.values()].to_dict()),
                               axis=1)   
    
        #Validation
        engines_fig = px.scatter(modified_engines, 
                                 x='eff_boost_thrust', 
                                 y='eff_travel_thrust', 
                                 text='basefilename_vro_original')
        engines_fig.update_traces(textposition='top center')
        engines_fig.update_layout(
                height=800,
                title_text='Boost vs travel thrust'
                )
        engines_fig.show()
        engines_fig.write_image(os.path.join(sum_outdir, 'modified_engines.png'))

        engines_fig_s = px.scatter(modified_engines[modified_engines['size'].isin(['s'])], 
                                 x='eff_boost_thrust', 
                                 y='eff_travel_thrust', 
                                 text='basefilename_vro_original')
        engines_fig_s.update_traces(textposition='top center')
        engines_fig_s.update_layout(
                height=800,
                title_text='Boost vs travel thrust, S ships'
                )
        engines_fig_s.show()
        engines_fig_s.write_image(os.path.join(sum_outdir, 'modified_engines_s.png'))

        modified_engines.to_csv(os.path.join(sum_outdir, 'modified_engines.csv'))    
    
    #--------------------------------------------------------------------------