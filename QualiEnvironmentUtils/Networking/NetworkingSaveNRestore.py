# coding=utf-8
from Sandbox import *
from Networking.ConfigFileManager import *
from Networking.PoolManager import *

import tftpy

#from TftpShared import *
import tempfile

class NetworkingSaveRestore():
    def __init__(self, sandbox):
        """
        Get the root directory for the config files on the tftp server
        :param SandboxBase sandbox:  The sandbox save & restore will be done in
        """
        self.sandbox = sandbox
        tftp_resource = self.sandbox.get_tftp_resource()
        if tftp_resource is not None:
            self.tftp_address = tftp_resource.address
            self.tftp_port = tftp_resource.get_attribute('TFTP Port')
            tftp_server_destination_path = tftp_resource.get_attribute("TFTP Network configs path")
            if tftp_server_destination_path != "":
                self.config_files_root = 'tftp://' + tftp_resource.address + "/" + tftp_server_destination_path
            else:
                self.sandbox.report_error("Failed to find the network's tftp path", raise_error=True,
                                          write_to_output_window=False)
        else:
            self.sandbox.report_error("Failed to find a tftp resource in the sandbox", raise_error=True,
                                      write_to_output_window=False)

            # pool_resource = self.sandbox.get_config_set_pool_resource()
            ##update all the resources' attributes with the data from the pool
            # if pool_resource is not None:
            #    pool_manager = PoolManager(sandbox = self.sandbox, pool_resource = pool_resource)
            #    pool_manager.push_data_from_pool_to_sandbox()

    # ----------------------------------
    # load_network_config(ResourceName,config_type, RestoreMethod=Override)
    # ResourceName - The name of the resource we would like to load the config onto
    # ConfigPath – the path to the configuration file, including the configuration file name.
    # The path should include the protocol type. This input is mandatory.
    # the configuration file name doesnt include “StartUp” or “Running”
    # Restore Method – optional, if empty the default value will be taken.
    # Possible values – Append or Override
    # Default value – Override
    # The command should fail if the configuration file name doesnt include “StartUp” or “Running”
    # config_stage - Gold, Base, Snapshot...
    # A path to a config file will look like ROOT_DIR/CONFIG_STAGE/BlueprintX/resourceY_ModelZ.cfg
    # e.g. tftp://configs/Gold/Large_Office/svl290-gg07-sw1_c3850.cfg
    # Base config is an exception. The blueprint's name is not in the path
    # e.g. tftp://configs/Base/svl290-gg07-sw1_c3850.cfg
    # ----------------------------------
    def load_config(self, config_stage, config_type, restore_method="Override", config_set_name='', ignore_models=[],
                    write_to_output=True):
        """
        Load the configuration from config files on the Blueprint's devices
        :param str config_stage:  The stage of the config e.g Gold, Base
        :param str config_type:  Possible values - StartUp or Running
        :param str restore_method: Optional. Restore method. Can be Append or Override
        :param str config_set_name: Optional. If we have multiple configuration sets for the same blueprint.
        the nam of the set selected by the user
        :param list[str] ignore_models: Optional. Models that should be ignored and not load config on the device
        """

        tftp_client = tftpy.TftpClient(self.tftp_address, self.tftp_port)
        config_set_pool_data = dict()
        #If there is a pool resource, get the pool data
        config_set_pool_resource = self.sandbox.get_config_set_pool_resource()
        if config_set_pool_resource is not None:
            config_set_pool_manager = PoolManager(sandbox=self.sandbox, pool_resource=config_set_pool_resource)
            config_set_pool_data = config_set_pool_manager.pool_data_to_dict()

        config_file_mgr = ConfigFileManager(self.sandbox)
        root_path = ''
        if config_stage.lower() == 'gold' or config_stage.lower() == 'snapshot':
            root_path = self.config_files_root + '/' + config_stage + '/' + self.sandbox.Blueprint_name + '/'
            if config_set_name != '':
                root_path = root_path + config_set_name + '/'
        elif config_stage.lower() == 'base':
            root_path = self.config_files_root + '/' + config_stage + '/'
        root_resources = self.sandbox.get_root_resources()
        """:type : list[ResourceBase]"""
        for resource in root_resources:
            live_status = resource.api_session.GetResourceLiveStatus(resource.name)
            #Check if needs to load the onfig to the device
            load_config_to_device = self._is_load_config_to_device(resource, ignore_models=ignore_models)
            if load_config_to_device:
                if 'Error' == live_status:
                    self.sandbox.report_info(resource.name + 'is not responding. Configuration will not be loaded to the device.',write_to_output_window=True)
                else:
                    if load_config_to_device:
                        try:
                            config_path = root_path + resource.alias + '_' + resource.model + '.cfg'

                            # Look for a template config file
                            tmp_template_file = tempfile.NamedTemporaryFile(delete=False)
                            tftp_template_config_path = root_path + resource.alias + '_' + resource.model + '.tm'
                            tftp_template_config_path = tftp_template_config_path.replace('tftp://' + self.tftp_address + "/", '')
                            tftp_template_config_path = tftp_template_config_path.replace(' ', '_')
                            try:
                                tftp_client.download(str(tftp_template_config_path), str(tmp_template_file.name))
                                tmp_concrete_file = tempfile.NamedTemporaryFile(delete=False)
                                config_file_mgr.create_concrete_config_from_template(tmp_template_file,
                                                                                     tmp_concrete_file,
                                                                                     config_set_pool_data)
                                tmp_template_file.close()
                                #tmp_template_file.delete()
                                concrete_file_path = root_path + 'temp/' + self.sandbox.id + '/' + resource.name + '_' + \
                                                     resource.model + '.cfg'
                                concrete_file_path = concrete_file_path.replace('tftp://' + self.tftp_address + "/",'')
                                concrete_file_path = concrete_file_path.replace(' ', '_')
                                #TODO - CHeck why the upload doesn't create new directories on the tftp server
                                tftp_client.upload(str(concrete_file_path), str(tmp_concrete_file.name))
                                tmp_concrete_file.close()
                                #tmp_concrete_file.delete()
                                config_path = concrete_file_path
                            except tftpy.TftpException:
                                tmp_template_file.close()

                            self.sandbox.report_info(
                                'Loading configuration for device: ' + resource.name + ' from:' + config_path, write_to_output)

                            resource.load_network_config(self.sandbox.id, config_path, config_type, restore_method)
                            self.sandbox.api_session.SetResourceLiveStatus(resource.name, 'Online')
                        except QualiError as qe:
                            err = "Failed to load configuration for device " + resource.name + ". " + str(qe)
                            self.sandbox.report_error(err, write_to_output_window=write_to_output, raise_error=False)
                            self.sandbox.api_session.SetResourceLiveStatus(resource.name, 'Error')
                        except :
                            err = "Failed to load configuration for device " + resource.name + \
                                  ". Unexpected error: " + traceback.format_exc()
                            self.sandbox.report_error(err, write_to_output_window=write_to_output, raise_error=False)
                            self.sandbox.api_session.SetResourceLiveStatus(resource.name, 'Error')


    # ----------------------------------
    # ----------------------------------
    def save_config(self, snapshot_name, config_type, ignore_models=[], write_to_output=True):
        """
        Load the configuration from the devices to the tftp
        :param str snapshot_name:  The name of the snapshot
        :param str config_type:  StartUp or Running
        """
        root_resources = self.sandbox.get_root_resources()

        config_path = self.config_files_root + '/Snapshots/' + snapshot_name

        # TODO: check - do I need to create the snapshot folder on the tfp server if it doesn't exist?
        for resource in root_resources:
            save_config_from_device = True
            for ignore_model in ignore_models:
                if resource.model.lower() == ignore_model.lower():
                    save_config_from_device = False
                    break
            if save_config_from_device:
                try:
                    self.sandbox.report_info(
                        'Saving configuration for device: ' + resource.name + ' to: ' + config_path, write_to_output)
                    resource.SaveNetworkConfig(self.sandbox.id, config_path, config_type)

                except QualiError as qe:
                    err = "Failed to save configuration for device " + resource.name + ". " + str(qe)
                    self.sandbox.report_error(err, write_to_output_window=write_to_output)
                except:
                    err = "Failed to save configuration for device " + resource.name + \
                          ". Unexpected error: " + str(sys.exc_info()[0])
                    self.sandbox.report_error(err, write_to_output_window=write_to_output)

    # ----------------------------------
    # Is this Sandbox originates from a snapshot Blueprint?
    # ----------------------------------
    def is_snapshot(self):
        # check if there is a directory with the Blueprint's name under the snapshots dir
        envDir = self.config_files_root + '/Snapshots/' + self.sandbox.Blueprint_name
        return os.path.isdir(envDir)

    # ----------------------------------
    # Check if need to load configuration to the given device
    # A device should not be in the ignored models list,
    # or should not have a "Disable Load Config" attribute set to True
    # in order to load configuration on it
    # ----------------------------------
    def _is_load_config_to_device(self, resource, ignore_models=[]):
        # check if the device is marked for not loading config during
        try:
            disable_load_config = resource.get_attribute("Disable Load Config")
            if disable_load_config:
                return False
        except QualiError:  # if attribute not found then assume load config in enabled
            pass
        for ignore_model in ignore_models:
            if resource.model.lower() == ignore_model.lower():
                return False
        return True
