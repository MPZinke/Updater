#!/usr/bin/env python3
# -*- coding: utf-8 -*-
__author__ = "MPZinke"

########################################################################################################################
#                                                                                                                      #
#   created by: MPZinke                                                                                                #
#   on 2021.10.07                                                                                                      #
#                                                                                                                      #
#   DESCRIPTION:                                                                                                       #
#   BUGS:                                                                                                              #
#   FUTURE:                                                                                                            #
#                                                                                                                      #
########################################################################################################################


import os;
from subprocess import call as subprocess_call, check_output as subprocess_check_output;
from threading import Lock;


from Global import *;
from Version import Version;
from Utility import Logger, time_to_midnight;
from Utility.ZThread import ZWidget;


class Updater(ZWidget):
	def __init__(self):
		ZWidget.__init__(self, "Updater");
		self._mutex = Lock();

		self.local_version = self.get_local_version();
		self.origin_Production_version = self.get_remote_version();


	# ——————————————————————————————————————————————————— ZWIDGET  ——————————————————————————————————————————————————— #

	# Increment versions, checking for DB updates. If found, update DB
	def _loop_process(self):
		self.origin_Production_version = self.get_remote_version();

		if(self.origin_Production_version != self.local_version):
			with self._mutex:
				self.update_git();
				self.update_db();
				self.restart_service();


	# Compliments of https://jacobbridges.github.io/post/how-many-seconds-until-midnight/
	def sleep_time(self) -> int:
		return time_to_midnight() + 30;  # give time to let event creators to do their thing


	# ————————————————————————————————————————————— GIT VERSION GETTERS  ————————————————————————————————————————————— #

	# Get current version from repo.
	def get_local_version(self):
		git_describe = subprocess_check_output(["git", "-C", REPO_DIR, "describe", "--tags"]);
		if(not git_describe):
			raise Exception("git describe was unable to get version number");

		describe_version = Version.version_string(git_describe.decode("utf-8"))
		if(not describe_version):
			raise Exception("Unable to search version number from git describe");
		return Version(describe_version);


	# Get remote version from remote repo.
	def get_remote_version(self):
		git_ls_remote = subprocess_check_output(["git", "-C", REPO_DIR, "ls-remote", "--tag", "origin"]);
		if(not git_ls_remote):
			raise Exception("git describe was unable to get version number");

		tag_strings = [Version.version_string(line) for line in git_ls_remote.decode("utf-8").rstrip().split("\n")];
		tag_strings = [tag_string for tag_string in tag_strings if(tag_string)];
		if(not tag_strings):
			raise Exception("Unable to find any version number from git describe");

		tags = [Version(tag) for tag in tag_strings];
		tags.sort();
		return tags[-1];


	# Checks whether provided branch name is the currently checked out branch.
	def branch_is_(self, branch_name: str) -> bool:
		if(not (git_branch := subprocess_check_output(["git", "-C", REPO_DIR, "branch"]))):
			return False;

		local_branches = git_branch.decode("utf-8").rstrip().split("\n");
		return f"* {branch_name}" in local_branches;


	# ———————————————————————————————————————————————————— UPDATE ———————————————————————————————————————————————————— #

	# Updates the DB incrementally with known update files.
	# Gets all files in folder except ./.add. Creates a Version object for all files. Sorts files by version number.
	#  Runs DB update file in mysql.
	def update_db(self):
		DB_update_folder = DB_DIR+"/Updates";
		if(not os.path.exists(DB_update_folder)):
			return;

		# Get all files that match versioning
		file_versions = [];
		for file in os.listdir(DB_update_folder):
			filepath = os.path.join(DB_update_folder, file);
			# Try to get the file's name excluding extension (valid filename example: v0.0.0.sql)
			version_string = Version.version_string(os.path.splitext(os.path.basename(filepath))[0]);

			# Include only files with proper version names within update range
			if(os.path.isfile(filepath) and version_string and self.version_is_usable(Version(version_string))):
				file_versions.append({"path": filepath, "version": Version(version_string)});

		file_versions.sort(key=lambda file_version : file_version["version"]);

		for file in file_versions:
			if(self.call_shell_command(["sudo", "mysql", "-u", "root", "<", file["path"]])):
				raise Exception(f"Failed to update DB with file {file['path']}");


	# Updates the Python and DB repository for the Hub.
	def update_git(self):
		if(not self.branch_is_("Production")):
			if(self.call_shell_command(["git", "-C", REPO_DIR, "checkout", "Production"])):
				raise Exception("Could not checkout Production branch");

		if(self.call_shell_command(["git", "-C", REPO_DIR, "pull"])):
			raise Exception("Could not pull repository");


	def restart_service(self):
		if(self.call_shell_command(["sudo", "systemctl", "restart", "UpdaterTestRepo.service"])):
			raise Exception("Could not restart systemctl service");


	# ——————————————————————————————————————————————————— UTILITY  ——————————————————————————————————————————————————— #

	def call_shell_command(self, params: list):
		with open(os.devnull, 'w') as FNULL:
			return subprocess_call(params, stdout=FNULL);


	# SUMMARY: Gets versions that are within version range (greater than current up to new version).
	# PARAMS: Takes the version object to compare to local_version and origin_Production_version.
	# DETAILS: This allows for all incremental DB updates to be processed in order.
	def version_is_usable(self, version: Version) -> bool:
		try:
			return self.local_version < version and version <= self.origin_Production_version;
		except Exception as error:
			Logger.log_error(error);
			return False;
